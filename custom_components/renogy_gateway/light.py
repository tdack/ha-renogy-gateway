"""Light platform for Renogy Gateway — dimmable DC output channels.

A channel is 'dimmable' when it exposes both a writable boolean '.state' field
and a writable integer '.ratio' field (0-100 %). These are combined into a
single HA light entity with brightness support.
"""

import contextlib
import math
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api.models import FieldSpec, RenogyDevice
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity

PARALLEL_UPDATES = 0


def _find_ratio_field(state_field: FieldSpec, device: RenogyDevice) -> FieldSpec | None:
    """Return the writable ratio sibling of a state field, if present."""
    ratio_sp = state_field.sp.rsplit(".", 1)[0] + ".ratio"
    return next((f for f in device.fields if f.sp == ratio_sp and f.writable), None)


def _is_light_state(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this is the '.state' field of a dimmable channel."""
    return (
        field.writable
        and field.field_type == 1  # bool
        and field.sp.endswith(".state")
        and _find_ratio_field(field, device) is not None
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Renogy light entities from a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data
    entities = []
    for device in coordinator.devices.values():
        for field in device.fields:
            if _is_light_state(field, device):
                ratio_field = _find_ratio_field(field, device)
                assert ratio_field is not None
                entities.append(RenogyLight(coordinator, device, field, ratio_field))
    async_add_entities(entities)


class RenogyLight(RenogyBaseEntity, RestoreEntity, LightEntity):
    """A dimmable DC output channel exposed as an HA light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        state_field: FieldSpec,
        ratio_field: FieldSpec,
    ) -> None:
        """Initialize the dimmable light entity with state and brightness fields."""
        super().__init__(coordinator, device, state_field)
        self._ratio_field = ratio_field
        self._ratio_value: int | None = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks and restore last known state."""
        await super().async_added_to_hass()
        # Also subscribe to the ratio field for brightness updates
        self._coordinator.register_telemetry_callback(
            self._ratio_field.sp, self._handle_ratio
        )
        cached_ratio = self._coordinator.get_value(self._ratio_field.sp)
        if cached_ratio is not None:
            with contextlib.suppress(TypeError, ValueError):
                self._ratio_value = int(cached_ratio)
        # Fall back to the last HA-recorded state only for whatever the
        # coordinator doesn't already have a live value for.
        if (self._value is None or self._ratio_value is None) and (
            last_state := await self.async_get_last_state()
        ) is not None:
            if self._value is None:
                self._value = last_state.state == "on"
            if (
                self._ratio_value is None
                and (brightness := last_state.attributes.get(ATTR_BRIGHTNESS))
                is not None
            ):
                self._ratio_value = round(int(brightness) / 255 * 100)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister all callbacks."""
        await super().async_will_remove_from_hass()
        self._coordinator.unregister_telemetry_callback(
            self._ratio_field.sp, self._handle_ratio
        )

    @callback
    def _handle_ratio(self, value: Any) -> None:
        """Handle incoming ratio (brightness) push."""
        with contextlib.suppress(TypeError, ValueError):
            self._ratio_value = int(value)
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool | None:
        """Return True if the channel reports an on state."""
        if self._value is None:
            return None
        return bool(self._value)

    @property
    def brightness(self) -> int | None:
        """Return brightness (0-255) derived from the ratio field."""
        if self._ratio_value is None:
            return None
        return math.ceil(self._ratio_value / 100 * 255)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, optionally setting brightness."""
        if ATTR_BRIGHTNESS in kwargs:
            ratio = round(int(kwargs[ATTR_BRIGHTNESS]) / 255 * 100)
            ratio = max(0, min(100, ratio))
            await self._coordinator.async_write(self._ratio_field.sp, ratio)
        await self._coordinator.async_write(self._field.sp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._coordinator.async_write(self._field.sp, False)
