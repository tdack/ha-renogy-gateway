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
# reliable signal here. Global because no namespace legitimately has a
# writable control under any of these names. Matched case-insensitively: a
# real capture (captures/*.har in the sibling renogy-gateway repo) shows the
# same quantity under inconsistently-cased leaf names on the same device
# (e.g. "voltage" alongside "battery_input.Voltage"), so an exact-case
# match alone misses half of them.
_FORCE_READONLY_LEAVES = frozenset(
    {
        "voltage",
        # Inverter (RIV1230RCH-24S) AC measurement leaves — packages/core/src/
        # registry.ts hardcodes these exact names as a fallback because no
        # capture ever shows gwm.get_model called for ac_input/ac_output/
        # battery_input; the dashboard's own human-curated labels confirm
        # they're pure readings ("AC input voltage", "AC input current",
        # "AC output power", "Battery input voltage").
        "ac_input_voltage",
        "ac_input_current",
        "ac_input_frequency",
        "output_watts",
    }
)

# Leaf SUFFIXES that are always a reading regardless of case. Confirmed live
# in captures/*.har: every lowercase "_today" daily accumulator in the
# inverter's inverter_history model (bat_chg_ah_today, bat_dischg_ah_today,
# generat_energy_today, used_energy_today, load_consum_line_today,
# line_chg_energy_today) reports ops=[1,2,4,5,7] — the literal write bit
# genuinely present, despite being a counter no one would ever "set".
_FORCE_READONLY_SUFFIXES = ("_today",)

# Same idea as _FORCE_READONLY_LEAVES, but scoped to a namespace because the
# leaf name is reused elsewhere for a genuine control — e.g. "state" is the
# real writable on/off field for distribution_box channels, but PROTOCOL.md
# §6 documents tpms.tp_state_N.{pressure,temperature,battery_status,online,
# state} as pure readings, and on some rigs the schema marks several of them
# writable anyway (observed live: pressure, online).
_FORCE_READONLY_LEAVES_BY_NAMESPACE: dict[str, frozenset[str]] = {
    "tpms": frozenset({"pressure", "temperature", "battery_status", "online", "state"}),
}


def _is_force_readonly(namespace: str, leaf: str) -> bool:
    """Return True if this (namespace, leaf) must be read-only regardless of
    what the schema's `ops` reports — see the constants above for evidence."""
    leaf_lower = leaf.lower()
    if leaf_lower in _FORCE_READONLY_LEAVES:
        return True
    if leaf_lower.endswith(_FORCE_READONLY_SUFFIXES):
        return True
    namespace_leaves = _FORCE_READONLY_LEAVES_BY_NAMESPACE.get(namespace, frozenset())
    return leaf_lower in {v.lower() for v in namespace_leaves}

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
        if _is_force_readonly(namespace, leaf):
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

        The RTM response data is a JSON-encoded string (sometimes
        double-encoded — parse up to twice). Confirmed shape via a real
        capture (captures/*.har in the sibling renogy-gateway repo) and
        packages/core/src/types.ts's ChannelConfig there:
        `{"distribution_box.dc_10a_1": {"name": "Bedroom Light",
        "channelEnable": true, "controlMode": 0, "icon": "...", ...}, ...}`
        — namespace-qualified keys, object values with a `name` field, NOT
        bare `{"dc_10a_1": "Bedroom Light"}` as PROTOCOL.md's prose
        description implied. An unset name reads back as the placeholder
        "--", not absent.
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

            labels: dict[str, str] = {}
            for key, value in inner.items():
                if not isinstance(value, dict):
                    continue
                name = value.get("name")
                if not isinstance(name, str) or not name or name == "--":
                    continue  # unset — the schema's default/humanized name wins
                channel_key = key.split(".", 1)[-1]  # strip "<namespace>." prefix
                labels[channel_key] = name
            return labels
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

    Real wire data (captures/*.har in the sibling renogy-gateway repo) always
    sends `ops` as a LIST of recognized codes drawn from {1,2,4,5,7} — never
    a bare combined integer. 5 and 7 are specific composite codes meaning
    "read + subscribe" (PROTOCOL.md §7.3: "4 = subscribe (5/7 also seen)");
    `write` is contributed ONLY by the literal code 1 being separately
    present in that list, never implied by decomposing 5 or 7 — mirroring
    packages/core/src/discovery.ts's opsToCaps exactly:
    `writable: o.some(v => v === OP_WRITE)` checks for literal 1 only.

    Confirmed against a real capture: the inverter's `Bat_Chg_Energy`
    reports ops=[2,4,5,7] (no literal 1) and is genuinely read-only, while
    `dc_output_ext.state` (PROTOCOL.md §7.4) reports ops=[1,2,4,5,7]
    (literal 1 present alongside 5/7) and is genuinely writable. Naively
    OR-ing raw integers together (decomposing 7 -> bits 0+1+2) sets the
    write bit from the literal value 7 alone — that's how pure sensor
    readings (TPMS pressure, shunt SOC, tank ratio, AC input current/
    voltage, daily energy counters, ...) were surfacing as Number/Select
    entities instead of sensors.

    A bare int is a test-fixture convenience only (real data is always a
    list) and is decomposed as a plain bitmask EXCEPT for 5/7, which get the
    same non-write treatment as in the list form, for consistency.
    """
    if isinstance(ops_raw, int):
        if ops_raw in (5, 7):
            return 2 | 4
        return ops_raw
    if isinstance(ops_raw, list):
        values = {int(v) for v in ops_raw}
        mask = 0
        if values & {2, 5, 7}:
            mask |= 2  # read
        if values & {4, 5, 7}:
            mask |= 4  # subscribe
        if 1 in values:
            mask |= 1  # write — ONLY from the literal code, never decomposed
        return mask
    return 0


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
