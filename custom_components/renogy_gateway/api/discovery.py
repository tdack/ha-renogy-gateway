"""Self-describing device and schema discovery for the Renogy DC Home API.

Three RPCs resolve any rig's full schema at runtime:
  1. gwm.devs   — device inventory behind a gateway
  2. gwm.get_product(pid)  — list of namespaces a device exposes
  3. gwm.get_model(namespace) — field schema for one namespace

User-assigned channel labels are read from userdata_str.config (double-encoded JSON).
"""

import asyncio
import json
import logging
from typing import Any

from ..const import HIDE_LEAVES
from .models import FieldSpec, RenogyDevice
from .rtm import RenogyRTM, RenogyRTMError

_LOGGER = logging.getLogger(__name__)

# Namespaces that carry only internal/meta data — don't surface as entities.
# Mirrors the dashboard/hass-bridge curation (packages/core/src/params.ts
# PARAM_HIDE_NS + apps/dashboard/src/worker/bridge.ts SKIP_SUBSCRIBE_NS) in
# the sibling renogy-gateway repo. Namespaces like gwmConfig, digital_input,
# signal, alternator, and battery_temp_sensor carry real telemetry/settings
# there and are intentionally NOT hidden here — only protocol/system
# internals that neither app ever surfaces are skipped. `scene` is handled
# by a dedicated platform instead of the generic field pipeline.
_SKIP_NAMESPACES = frozenset(
    {
        "thing",
        "gwm",
        "version_ctrl",
        "driving_mode",  # special-cased below for ctrl_sp_blacklist
        "cloud",
        "customAlarm",
        "scene",
        "charger_history",
        "userdata_str",
        "sys_data_str",
        "factoryConfig",
        "ems_gw",
        "buzzer",
        "gyro",
        "dev_ota",
        "ssh_debug",
        "rtc_sync",
    }
)

# Field types that can be meaningful HA entities
_ENTITY_TYPES = frozenset({1, 2, 3})  # bool, int, float

# Leaves the schema marks writable (ops includes the write bit) but which are
# actually just a reading, not a setting — the schema marks almost every
# field writable, including protocol internals, so `ops` alone isn't a
# reliable signal here.
_FORCE_READONLY_LEAVES = frozenset({"voltage"})

# Maximum concurrent RPCs to avoid overwhelming the gateway
_MAX_CONCURRENT = 4


class RenogyDiscovery:
    """Discovers devices and their field schemas from a connected RTM session."""

    def __init__(self, rtm: RenogyRTM) -> None:
        """Initialize the discovery helper with a connected RTM client."""
        self._rtm = rtm
        # Cache resolved model schemas: namespace → list of raw sp dicts
        self._model_cache: dict[str, list[dict]] = {}

    async def discover(self, gateway_did_str: str) -> list[RenogyDevice]:
        """Return fully resolved devices behind the given gateway.

        Steps:
          1. gwm.devs (two-step RPC) → device inventory
          2. gwm.get_product per device → namespace list
          3. gwm.get_model per namespace → field schema
          4. userdata_str.config → user-assigned channel labels
        """
        devices_raw = await self._get_devices(gateway_did_str)
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async def resolve(raw: dict) -> RenogyDevice | None:
            async with sem:
                return await self._resolve_device(raw)

        results = await asyncio.gather(*(resolve(r) for r in devices_raw))
        return [d for d in results if d is not None]

    # ------------------------------------------------------------------
    # Step 1: device inventory via gwm.devs
    # ------------------------------------------------------------------

    async def _get_devices(self, gateway_did_str: str) -> list[dict]:
        """Run the two-step gwm.devs RPC to list child devices."""
        gw_did = int(gateway_did_str)
        # Step 1: register gateway into RTM session
        try:
            await self._rtm.rpc("1/gwm.devs", {"dids": [gw_did]})
        except RenogyRTMError:
            _LOGGER.debug("gwm.devs step-1 failed; proceeding anyway")

        # Step 2: list devices
        result = await self._rtm.rpc("1/gwm.devs", {"gatewayId": gw_did})
        devs = result.get("devs") if result else []
        return devs or []

    # ------------------------------------------------------------------
    # Step 2 + 3: resolve one device
    # ------------------------------------------------------------------

    async def _resolve_device(self, raw: dict) -> RenogyDevice | None:
        """Resolve namespaces and fields for one device entry from gwm.devs."""
        did_str = str(raw.get("did_str") or raw.get("did", ""))
        pid = raw.get("pid", "")
        sku = raw.get("sku", "")
        name = raw.get("text") or raw.get("name") or sku or pid
        online = bool(raw.get("online"))

        if not did_str or not pid:
            return None

        namespaces = await self._get_namespaces(pid)
        if not namespaces:
            _LOGGER.debug("No namespaces for pid=%s, skipping device", pid)
            return None

        fields: list[FieldSpec] = []
        for ns in namespaces:
            if ns in _SKIP_NAMESPACES:
                continue
            ns_fields = await self._get_fields(did_str, ns)
            fields.extend(ns_fields)

        # Fetch user-assigned channel labels if the device has userdata_str
        if "userdata_str" in namespaces:
            label_map = await self._get_user_labels(did_str)
            if label_map:
                _apply_labels(fields, label_map)

        blacklist: frozenset[str] = frozenset()
        if "driving_mode" in namespaces:
            blacklist = await self._get_ctrl_sp_blacklist(did_str)

        return RenogyDevice(
            did_str=did_str,
            pid=pid,
            sku=sku,
            name=name,
            online=online,
            fields=fields,
            ctrl_sp_blacklist=blacklist,
        )

    async def _get_namespaces(self, pid: str) -> list[str]:
        """Return the namespace list for a product ID."""
        try:
            result = await self._rtm.rpc("1/gwm.get_product", {"name": pid})
        except RenogyRTMError:
            _LOGGER.debug("get_product(%s) failed", pid)
            return []
        return list(result.get("models") or []) if result else []

    # ------------------------------------------------------------------
    # Step 3: resolve field schema for a namespace
    # ------------------------------------------------------------------

    async def _get_fields(self, did_str: str, namespace: str) -> list[FieldSpec]:
        """Resolve field specs for one namespace, with caching."""
        raw_sps = await self._get_model(namespace)
        fields: list[FieldSpec] = []
        for sp_dict in raw_sps:
            specs = await self._expand_sp(did_str, namespace, sp_dict, frozenset())
            fields.extend(specs)
        return fields

    async def _expand_sp(
        self,
        did_str: str,
        namespace: str,
        sp_dict: dict,
        visiting: frozenset[str],
        prefix: str = "",
    ) -> list[FieldSpec]:
        """Recursively expand one raw sp dict into zero or more FieldSpecs.

        Handles 'ref' (sp is an object of another model, resolved by name —
        e.g. tpms `tp_state_N` -> model `tpms_state`) and inline type-7
        objects (literal 'fields' list) the same way: by recursing with the
        sp's own name appended to the path prefix.
        """
        name = sp_dict.get("name", "")
        field_type = sp_dict.get("type", 0)
        full_name = f"{prefix}{name}" if prefix else name

        if field_type == 8:  # RPC method — not a telemetry field
            return []

        ref = sp_dict.get("ref")
        if ref:
            if ref in visiting:
                return []  # cycle guard
            ref_sps = await self._get_model(ref)
            nested_visiting = visiting | {ref}
            results: list[FieldSpec] = []
            for child in ref_sps:
                results.extend(
                    await self._expand_sp(
                        did_str, namespace, child, nested_visiting, f"{full_name}."
                    )
                )
            return results

        if field_type == 7:  # inline object — recurse into literal fields
            results = []
            for child in sp_dict.get("fields") or []:
                results.extend(
                    await self._expand_sp(
                        did_str, namespace, child, visiting, f"{full_name}."
                    )
                )
            return results

        ops = _parse_ops(sp_dict.get("ops", []))
        if field_type not in _ENTITY_TYPES or not ops:
            return []

        leaf = full_name.rsplit(".", 1)[-1]
        if leaf in HIDE_LEAVES:
            return []  # protocol internal / maintenance command, not a setting
        if leaf in _FORCE_READONLY_LEAVES:
            ops &= ~1  # strip the write bit — a reading, not a setting

        sp = f"{did_str}/{namespace}.{full_name}"
        return [
            FieldSpec(
                sp=sp,
                name=full_name,
                field_type=field_type,
                ops=ops,
                unit=sp_dict.get("unit") or None,
                min_value=_to_float(sp_dict.get("min")),
                max_value=_to_float(sp_dict.get("max")),
                options=sp_dict.get("options") or None,
                precision=int(sp_dict.get("precision") or 0),
            )
        ]

    async def _get_model(self, namespace: str) -> list[dict]:
        """Fetch and cache the raw sp list for a namespace (recursive inherit)."""
        if namespace in self._model_cache:
            return self._model_cache[namespace]

        try:
            result = await self._rtm.rpc("1/gwm.get_model", {"name": namespace})
        except RenogyRTMError:
            _LOGGER.debug("get_model(%s) failed", namespace)
            self._model_cache[namespace] = []
            return []

        if not result:
            self._model_cache[namespace] = []
            return []

        raw_sps: list[dict] = list(result.get("sps") or [])

        # Resolve 'inherit' — merge parent model's sps (child overrides by name)
        parent_ns = result.get("inherit")
        if parent_ns:
            parent_sps = await self._get_model(parent_ns)
            child_names = {s.get("name") for s in raw_sps}
            merged = [s for s in parent_sps if s.get("name") not in child_names]
            merged.extend(raw_sps)
            raw_sps = merged

        self._model_cache[namespace] = raw_sps
        return raw_sps

    # ------------------------------------------------------------------
    # Step 4: user-assigned channel labels
    # ------------------------------------------------------------------

    async def _get_user_labels(self, did_str: str) -> dict[str, str]:
        """Read userdata_str.config and return {channel_key: label}.

        The RTM response data is a double-encoded JSON string — parse twice.
        """
        sp = f"{did_str}/userdata_str.config"
        try:
            raw_value = await self._rtm.read(sp)
        except (RenogyRTMError, TimeoutError):
            _LOGGER.debug("Could not read userdata_str.config for %s", did_str)
            return {}

        if not raw_value:
            return {}

        # Double-encoded: data is a JSON string → parse once → get another string → parse again
        try:
            if isinstance(raw_value, str):
                inner = json.loads(raw_value)
            else:
                inner = raw_value

            if isinstance(inner, str):
                inner = json.loads(inner)

            if not isinstance(inner, dict):
                return {}

            # The map has channel keys directly: {"dc_10a_1": "Bedroom Light", ...}
            return {k: v for k, v in inner.items() if isinstance(v, str) and v}
        except (json.JSONDecodeError, TypeError):
            _LOGGER.debug("Failed to parse userdata_str.config for %s", did_str)
            return {}

    # ------------------------------------------------------------------
    # Step 5: control blacklist
    # ------------------------------------------------------------------

    async def _get_ctrl_sp_blacklist(self, did_str: str) -> frozenset[str]:
        """Read driving_mode.ctrl_sp_blacklist.

        Returns the relative field paths the device firmware refuses writes for.
        """
        sp = f"{did_str}/driving_mode.ctrl_sp_blacklist"
        try:
            raw_value = await self._rtm.read(sp)
        except (RenogyRTMError, TimeoutError):
            _LOGGER.debug("Could not read ctrl_sp_blacklist for %s", did_str)
            return frozenset()

        if isinstance(raw_value, str):
            try:
                raw_value = json.loads(raw_value)
            except json.JSONDecodeError:
                return frozenset()

        if not isinstance(raw_value, list):
            return frozenset()

        return frozenset(str(v) for v in raw_value if isinstance(v, str))


# ------------------------------------------------------------------
# Field resolution helpers
# ------------------------------------------------------------------


def _parse_ops(ops_raw: Any) -> int:
    """Convert raw `ops` (an int, or a list of recognized op codes) into our
    internal {1: write, 2: read, 4: subscribe} bitmask.

    `ops` is NOT a generic bitmask to OR together — 5 is a specific composite
    code meaning "read + subscribe, NOT write" despite 5 == 4+1 in binary
    (PROTOCOL.md §7.3: "4 = subscribe (5/7 also seen)"). Mirrors
    packages/core/src/discovery.ts's opsToCaps in the sibling renogy-gateway
    repo exactly: `writable` only ever fires for the literal value 1; `5`
    explicitly adds read+subscribe but never write. Naively OR-ing raw
    integers (5 → bits 0+2 set) misread ops=5 as writable, which is how pure
    sensor readings (TPMS pressure, shunt SOC, tank ratio, ...) were
    surfacing as Number/Select entities instead of sensors.
    """
    if isinstance(ops_raw, int):
        values = [ops_raw]
    elif isinstance(ops_raw, list):
        values = [int(v) for v in ops_raw]
    else:
        return 0

    mask = 0
    for v in values:
        if v == 5:
            mask |= 2 | 4  # read + subscribe, deliberately NOT write
        else:
            mask |= v
    return mask


def _to_float(v: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _apply_labels(fields: list[FieldSpec], label_map: dict[str, str]) -> None:
    """Apply user-assigned labels to fields by channel key.

    The channel key is the second segment of the field path, e.g.:
      'dc_10a_1' from 'distribution_box.dc_10a_1.state'

    All co-channel fields share the same label (state, power, ratio, current...).
    """
    for f in fields:
        key = f.channel_key
        if key and key in label_map:
            f.user_label = label_map[key]
