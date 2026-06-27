"""Renogy Gateway coordinator — manages the RTM connection and entity state."""

import asyncio
from collections.abc import Callable
import contextlib
import logging
import re
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import aiohttp_client

from .api.auth import RenogyAuth, RenogyAuthError, RenogyConnectionError
from .api.discovery import RenogyDiscovery
from .api.models import FieldSpec, RenogyDevice, SceneInfo, TokenSet
from .api.rest import RenogyREST
from .api.rtm import RenogyRTM, RenogyRTMError
from .const import (
    CONF_DEVICE_UUID,
    CONF_GATEWAY_ID,
    CONF_REFRESH_TOKEN,
    CONF_RTM_DID,
    CONF_RTM_TOKEN,
    DOMAIN,
    RTM_RECONNECT_DELAY_MAX,
    RTM_RECONNECT_DELAY_MIN,
)

_LOGGER = logging.getLogger(__name__)

# Multi-instance schema slots (tanks, temp probes, TPMS sensors) that the
# schema always advertises regardless of whether the rig actually has that
# sensor wired up. A slot with no live readings for any of its fields is a
# phantom — drop it instead of showing it stuck at "unknown" forever.
_INSTANCE_PATTERNS = (
    re.compile(r"^ai_\d+$"),
    re.compile(r"^temp_\d+$"),
    re.compile(r"^tp_state_\d+$"),
)

type RenogyConfigEntry = ConfigEntry[RenogyCoordinator]

AvailabilityCallback = Callable[[bool], None]
TelemetryCallback = Callable[[Any], None]
SceneCallback = Callable[[], None]


class RenogyCoordinator:
    """Coordinates the Renogy RTM WebSocket connection and dispatches telemetry."""

    def __init__(self, hass: HomeAssistant, entry: RenogyConfigEntry) -> None:
        """Initialize the coordinator, auth, RTM client, and token persistence."""
        self._hass = hass
        self._entry = entry
        self._session: aiohttp.ClientSession = aiohttp_client.async_get_clientsession(
            hass
        )

        async def _persist_tokens(tokens: TokenSet) -> None:
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_RTM_TOKEN: tokens.rtm_token,
                    CONF_RTM_DID: tokens.rtm_did,
                    CONF_DEVICE_UUID: tokens.device_uuid,
                },
            )

        self._auth = RenogyAuth(self._session, _persist_tokens)
        self._rest = RenogyREST(self._session, self._auth)
        self._rtm = RenogyRTM(self._session, self._auth)
        self._discovery = RenogyDiscovery(self._rtm)

        # Discovered devices keyed by did_str
        self.devices: dict[str, RenogyDevice] = {}

        # Scenes (Manual + Auto) keyed by scene id — fetched via REST, not
        # the field-discovery pipeline (PROTOCOL.md §8).
        self.scenes: dict[str, SceneInfo] = {}
        self._scene_callbacks: list[SceneCallback] = []

        # Last known value per sp — seeded by an initial read, kept fresh by
        # telemetry pushes. Lets entities show a value immediately on add
        # instead of waiting indefinitely for the next push.
        self._last_values: dict[str, Any] = {}

        # Per-sp telemetry callbacks: sp → list of entity callbacks
        self._telemetry_callbacks: dict[str, list[TelemetryCallback]] = {}
        # Availability callbacks fired when RTM connect/disconnect occurs
        self._availability_callbacks: list[AvailabilityCallback] = []

        self._reconnect_task: asyncio.Task | None = None
        self._shutdown = False

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Connect and perform initial discovery. Raises ConfigEntryNotReady on failure."""
        from homeassistant.exceptions import ConfigEntryNotReady  # noqa: PLC0415

        # Restore tokens from persisted config entry data
        data = self._entry.data
        if data.get(CONF_ACCESS_TOKEN):
            self._auth.set_tokens(
                TokenSet(
                    access_token=data[CONF_ACCESS_TOKEN],
                    refresh_token=data[CONF_REFRESH_TOKEN],
                    rtm_token=data[CONF_RTM_TOKEN],
                    rtm_did=data[CONF_RTM_DID],
                    device_uuid=data[CONF_DEVICE_UUID],
                )
            )

        try:
            await self._connect_and_discover()
        except (RenogyConnectionError, RenogyRTMError) as err:
            raise ConfigEntryNotReady(f"Cannot connect to Renogy: {err}") from err
        except RenogyAuthError as err:
            from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: PLC0415

            raise ConfigEntryAuthFailed(f"Renogy authentication failed: {err}") from err

    async def _connect_and_discover(self) -> None:
        """Open RTM, run discovery, subscribe all fields."""
        gateway_id = self._entry.data[CONF_GATEWAY_ID]

        await self._rtm.connect()
        self._rtm.set_telemetry_dispatcher(self._dispatch_telemetry)

        self.devices = {
            d.did_str: d for d in await self._discovery.discover(gateway_id)
        }
        _LOGGER.debug(
            "Discovered %d devices behind gateway %s", len(self.devices), gateway_id
        )

        all_fields = [f for device in self.devices.values() for f in device.fields]

        # Seed every readable field with its current value. Write-only-no-
        # subscribe config fields would otherwise never get a value (they
        # never push), and subscribable fields would sit on "unknown" until
        # their next push after every reload.
        readable_fields = [f for f in all_fields if f.readable]
        sem_read = asyncio.Semaphore(4)

        async def _read_initial(field: FieldSpec) -> None:
            async with sem_read:
                try:
                    value = await self._rtm.read(field.sp)
                except (RenogyRTMError, TimeoutError):
                    _LOGGER.debug("Initial read failed for %s", field.sp)
                    return
                self._last_values[field.sp] = value

        await asyncio.gather(*(_read_initial(f) for f in readable_fields))

        self._drop_phantom_instances()
        all_fields = [f for device in self.devices.values() for f in device.fields]

        # Subscribe all subscribable fields
        fields_to_subscribe = [f for f in all_fields if f.subscribable]
        sem_sub = asyncio.Semaphore(4)

        async def _subscribe(sp: str) -> None:
            async with sem_sub:
                try:
                    await self._rtm.subscribe(sp)
                except (RenogyRTMError, TimeoutError):
                    _LOGGER.debug("Subscribe failed for %s", sp)

        await asyncio.gather(*(_subscribe(f.sp) for f in fields_to_subscribe))
        _LOGGER.debug("Subscribed to %d fields", len(fields_to_subscribe))

        await self._refresh_scenes(gateway_id)

    async def _refresh_scenes(self, gateway_id: str) -> None:
        """Fetch Manual + Auto scenes for the gateway (PROTOCOL.md §8.1).

        Scenes are optional polish — a REST failure here shouldn't block
        startup of the rest of the integration.
        """
        try:
            scenes = await self._rest.get_scenes(gateway_id)
        except RenogyConnectionError:
            _LOGGER.debug("Failed to fetch scenes for gateway %s", gateway_id)
            return
        self.scenes = {s.id: s for s in scenes}
        _LOGGER.debug("Discovered %d scenes", len(self.scenes))

    def _drop_phantom_instances(self) -> None:
        """Remove fields for multi-instance slots with no live seeded value.

        The schema advertises every tank/temp-probe/TPMS slot a model
        supports, whether or not this specific rig has that sensor wired up.
        Settings-type fields (calibration_pressure, alarm thresholds,
        axle_num, ...) answer with a stable firmware default even for an
        unbound slot, so liveness must be judged from genuine *readings*
        (non-writable fields) only — a writable field's default value would
        otherwise make every unbound slot look live.
        """
        for device in self.devices.values():
            by_instance: dict[str, list[FieldSpec]] = {}
            other_fields: list[FieldSpec] = []
            for f in device.fields:
                key = f.channel_key
                if key and any(p.match(key) for p in _INSTANCE_PATTERNS):
                    by_instance.setdefault(key, []).append(f)
                else:
                    other_fields.append(f)

            live_fields = [
                f
                for fields in by_instance.values()
                if any(
                    not f.writable and self._last_values.get(f.sp) is not None
                    for f in fields
                )
                for f in fields
            ]
            device.fields = other_fields + live_fields

    async def async_shutdown(self) -> None:
        """Disconnect and clean up."""
        self._shutdown = True
        if self._reconnect_task:
            self._reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reconnect_task
        await self._rtm.disconnect()

    # ------------------------------------------------------------------
    # Telemetry dispatch
    # ------------------------------------------------------------------

    def _dispatch_telemetry(self, sp: str, value: Any) -> None:
        """Called by RTM for every op-7 push; routes to registered entity callbacks."""
        self._last_values[sp] = value
        for cb in self._telemetry_callbacks.get(sp, []):
            try:
                cb(value)
            except Exception:
                _LOGGER.exception("Error in telemetry callback for sp=%s", sp)

    def get_value(self, sp: str) -> Any | None:
        """Return the last known value for a field, or None if not yet known."""
        return self._last_values.get(sp)

    # ------------------------------------------------------------------
    # Entity registration
    # ------------------------------------------------------------------

    @callback
    def register_telemetry_callback(
        self, sp: str, callback_fn: TelemetryCallback
    ) -> None:
        """Register an entity callback for a specific topic path."""
        self._telemetry_callbacks.setdefault(sp, []).append(callback_fn)

    @callback
    def unregister_telemetry_callback(
        self, sp: str, callback_fn: TelemetryCallback
    ) -> None:
        """Remove a previously registered entity callback."""
        cbs = self._telemetry_callbacks.get(sp, [])
        with contextlib.suppress(ValueError):
            cbs.remove(callback_fn)
        if not cbs:
            self._telemetry_callbacks.pop(sp, None)

    @callback
    def register_availability_callback(self, cb: AvailabilityCallback) -> None:
        """Register a callback fired when RTM availability changes."""
        self._availability_callbacks.append(cb)

    @callback
    def unregister_availability_callback(self, cb: AvailabilityCallback) -> None:
        """Remove a previously registered availability callback."""
        with contextlib.suppress(ValueError):
            self._availability_callbacks.remove(cb)

    def _fire_availability(self, available: bool) -> None:
        for cb in self._availability_callbacks:
            try:
                cb(available)
            except Exception:
                _LOGGER.exception("Error in availability callback")

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    async def async_write(self, sp: str, value: Any) -> None:
        """Write a value to a controllable RTM field."""
        from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

        did_str, _, relative = sp.partition("/")
        device = self.devices.get(did_str)
        if device is not None and relative in device.ctrl_sp_blacklist:
            raise HomeAssistantError(
                f"{sp} is blocked from control by the device's control blacklist"
            )

        try:
            ack = await self._rtm.write(sp, value)
            code = ack.get("code") if ack else None
            if code not in (0, 14):
                _LOGGER.warning("Write to %s returned unexpected code: %s", sp, code)
        except (RenogyRTMError, TimeoutError) as err:
            _LOGGER.error("Write to %s failed: %s", sp, err)
            raise

    async def async_run_scene(self, scene_id: str) -> None:
        """Execute a Manual scene (PROTOCOL.md §8.3).

        Runs a batch of writes to physical circuits — the scene must already
        exist in self.scenes (i.e. came from a successful discovery fetch).
        """
        from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

        scene = self.scenes.get(scene_id)
        if scene is None:
            raise HomeAssistantError(f"Unknown scene id {scene_id}")

        try:
            ack = await self._rtm.run_scene(scene.gateway_did, int(scene_id))
            code = ack.get("code") if ack else None
            if code not in (0, 14):
                _LOGGER.warning(
                    "Run scene %s returned unexpected code: %s", scene_id, code
                )
        except (RenogyRTMError, TimeoutError) as err:
            _LOGGER.error("Run scene %s failed: %s", scene_id, err)
            raise

    async def async_set_scene_open(self, scene_id: str, is_open: bool) -> None:
        """Arm/disarm an Auto scene (PROTOCOL.md §8.1/§8.2)."""
        scene = self.scenes.get(scene_id)
        if scene is None:
            from homeassistant.exceptions import HomeAssistantError  # noqa: PLC0415

            raise HomeAssistantError(f"Unknown scene id {scene_id}")

        await self._rest.update_scene(scene, is_open=is_open)
        scene.is_open = is_open
        self._fire_scene_callbacks()

    @callback
    def register_scene_callback(self, cb: SceneCallback) -> None:
        """Register a callback fired whenever any scene's state changes."""
        self._scene_callbacks.append(cb)

    @callback
    def unregister_scene_callback(self, cb: SceneCallback) -> None:
        """Remove a previously registered scene callback."""
        with contextlib.suppress(ValueError):
            self._scene_callbacks.remove(cb)

    def _fire_scene_callbacks(self) -> None:
        for cb in self._scene_callbacks:
            try:
                cb()
            except Exception:
                _LOGGER.exception("Error in scene callback")

    # ------------------------------------------------------------------
    # RTM reconnection
    # ------------------------------------------------------------------

    def schedule_reconnect(self) -> None:
        """Schedule a reconnect attempt in the background."""
        if self._shutdown or self._reconnect_task:
            return
        self._reconnect_task = self._hass.async_create_background_task(
            self._reconnect_loop(), f"{DOMAIN}_reconnect"
        )

    async def _reconnect_loop(self) -> None:
        """Reconnect with exponential backoff, marking entities unavailable between attempts."""
        self._fire_availability(False)
        delay = RTM_RECONNECT_DELAY_MIN
        while not self._shutdown:
            _LOGGER.debug("RTM reconnecting in %ds", delay)
            await asyncio.sleep(delay)
            try:
                await self._rtm.disconnect()
                await self._connect_and_discover()
                self._fire_availability(True)
                _LOGGER.info("RTM reconnected successfully")
                break
            except (
                RenogyAuthError,
                RenogyConnectionError,
                RenogyRTMError,
                aiohttp.ClientError,
                TimeoutError,
            ):
                _LOGGER.debug("RTM reconnect attempt failed")
                delay = min(delay * 2, RTM_RECONNECT_DELAY_MAX)
        self._reconnect_task = None
