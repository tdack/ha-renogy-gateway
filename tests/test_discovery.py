"""Tests for the Renogy Gateway discovery module."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.renogy_gateway.api.discovery import (
    _SKIP_NAMESPACES,
    RenogyDiscovery,
    _apply_labels,
    _parse_ops,
)
from custom_components.renogy_gateway.api.models import FieldSpec
from custom_components.renogy_gateway.api.rtm import RenogyRTMError


def _make_field(name: str, ops: int, field_type: int = 3) -> FieldSpec:
    return FieldSpec(
        sp=f"123/ns.{name}",
        name=name,
        field_type=field_type,
        ops=ops,
    )


async def test_apply_labels_sets_user_label() -> None:
    """Channel labels are applied to all co-channel fields."""
    fields = [
        FieldSpec(
            sp="123/distribution_box.dc_10a_1.state",
            name="dc_10a_1.state",
            field_type=1,
            ops=7,
        ),
        FieldSpec(
            sp="123/distribution_box.dc_10a_1.power",
            name="dc_10a_1.power",
            field_type=2,
            ops=6,
        ),
        FieldSpec(
            sp="123/distribution_box.dc_20a_1.state",
            name="dc_20a_1.state",
            field_type=1,
            ops=7,
        ),
    ]
    label_map = {"dc_10a_1": "Bedroom Light", "dc_20a_1": "Sockets"}
    _apply_labels(fields, label_map)

    assert fields[0].user_label == "Bedroom Light"
    assert fields[1].user_label == "Bedroom Light"
    assert fields[2].user_label == "Sockets"


async def test_user_label_double_parse() -> None:
    """userdata_str.config is sometimes double-encoded JSON — must handle
    parsing it twice. Real shape confirmed via captures/*.har in the sibling
    renogy-gateway repo: namespace-qualified keys
    ("distribution_box.dc_10a_1"), object values with a "name" field —
    NOT bare {"dc_10a_1": "Bedroom Light"} as PROTOCOL.md's prose implied."""
    inner_dict = {
        "distribution_box.dc_10a_1": {"name": "Bedroom Light", "channelEnable": True},
        "distribution_box.relay_3": {"name": "Cooling Fan", "channelEnable": True},
    }
    inner_str = json.dumps(inner_dict)
    outer_str = json.dumps(inner_str)

    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=outer_str)

    discovery = RenogyDiscovery(rtm)
    labels = await discovery._get_user_labels("123")
    assert labels == {"dc_10a_1": "Bedroom Light", "relay_3": "Cooling Fan"}


async def test_user_label_already_single_parsed() -> None:
    """If data is already a dict (single parse), handle gracefully."""
    inner_dict = {
        "distribution_box.dc_10a_1": {"name": "Bedroom Light", "channelEnable": True}
    }

    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=inner_dict)

    discovery = RenogyDiscovery(rtm)
    labels = await discovery._get_user_labels("123")
    assert labels == {"dc_10a_1": "Bedroom Light"}


async def test_user_label_real_capture_payload() -> None:
    """Exact payload captured live (captures/*.har), single-JSON-encoded
    (not double, despite PROTOCOL.md describing it that way) — exercises
    icon/controlMode fields being ignored and the "--" placeholder being
    treated as unset rather than a literal channel name."""
    raw = (
        '{"distribution_box.ai_1": {"channelEnable": true, "name": "Front", '
        '"tankUsage": 0}, "distribution_box.ai_2": {"channelEnable": true, '
        '"name": "--", "tankUsage": 0}, "distribution_box.dc_10a_1": '
        '{"channelEnable": true, "controlMode": 0, "icon": "##ic_courtesy_light##", '
        '"name": "Bedroom Light", "showCurrent": false, "showPower": false}}'
    )
    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=raw)

    discovery = RenogyDiscovery(rtm)
    labels = await discovery._get_user_labels("123")

    assert labels == {"ai_1": "Front", "dc_10a_1": "Bedroom Light"}
    assert "ai_2" not in labels  # "--" placeholder == unset


async def test_user_label_parse_failure_returns_empty() -> None:
    """Malformed data returns empty dict without raising."""
    rtm = MagicMock()
    rtm.read = AsyncMock(return_value="not json at all {{{{")

    discovery = RenogyDiscovery(rtm)
    labels = await discovery._get_user_labels("123")
    assert labels == {}


async def test_get_fields_resolves_ref() -> None:
    """A sp with 'ref' resolves the referenced model and prefixes its fields.

    Mirrors TPMS tp_state_N -> model tpms_state.
    """
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        side_effect=[
            {
                "sps": [
                    {"name": "tp_state_1", "type": 7, "ref": "tpms_state"},
                ]
            },
            {
                "sps": [
                    {"name": "pressure", "type": 3, "ops": 6, "unit": "kPa"},
                    {"name": "online", "type": 1, "ops": 6},
                ]
            },
        ]
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "tpms")

    assert {f.sp for f in fields} == {
        "123/tpms.tp_state_1.pressure",
        "123/tpms.tp_state_1.online",
    }
    assert {f.name for f in fields} == {"tp_state_1.pressure", "tp_state_1.online"}


async def test_voltage_leaf_forced_readonly() -> None:
    """'voltage' is schema-writable but should surface as a sensor, not a number.

    The schema marks almost every field writable, including readings — the
    app's own curation overrides 'voltage' specifically back to read-only.
    """
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {"name": "voltage", "type": 3, "ops": 7, "unit": "V"},
                {"name": "current", "type": 3, "ops": 6, "unit": "A"},
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "charger")

    by_name = {f.name: f for f in fields}
    assert by_name["voltage"].writable is False
    assert by_name["current"].writable is False


@pytest.mark.parametrize(
    ("ops_raw", "expected"),
    [
        (1, {"writable": True, "readable": False, "subscribable": False}),
        (2, {"writable": False, "readable": True, "subscribable": False}),
        (4, {"writable": False, "readable": False, "subscribable": True}),
        # 5 is a specific composite code meaning "read + subscribe, NOT
        # write" — despite 5 == 4+1 in binary. Mirrors
        # packages/core/src/discovery.ts's opsToCaps in the sibling
        # renogy-gateway repo exactly. This is the real-world regression:
        # TPMS pressure / shunt SOC report ops=5 and were being misread as
        # writable by a naive bitwise OR, surfacing them as Configuration
        # (Number) entities instead of sensors.
        (5, {"writable": False, "readable": True, "subscribable": True}),
        # 7 gets the same treatment as 5 — it's also just "read + subscribe"
        # unless the literal write code 1 is separately present. Confirmed
        # against a real capture: the inverter's Bat_Chg_Energy reports
        # ops=[2,4,5,7] (no literal 1) and is genuinely read-only.
        (7, {"writable": False, "readable": True, "subscribable": True}),
        (
            [1, 2, 4, 5, 7],
            {"writable": True, "readable": True, "subscribable": True},
        ),  # PROTOCOL.md §7.4's dc_output_ext.state example — literal 1 present
        ([2, 4, 5, 7], {"writable": False, "readable": True, "subscribable": True}),
        ([5], {"writable": False, "readable": True, "subscribable": True}),
        ([7], {"writable": False, "readable": True, "subscribable": True}),
    ],
)
def test_parse_ops_matches_dashboard_semantics(
    ops_raw: int | list[int], expected: dict[str, bool]
) -> None:
    """ops is a set of recognized codes, not a freely-combinable bitmask."""
    ops = _parse_ops(ops_raw)
    assert bool(ops & 1) is expected["writable"]
    assert bool(ops & 2) is expected["readable"]
    assert bool(ops & 4) is expected["subscribable"]


async def test_tpms_pressure_ops5_is_not_writable() -> None:
    """A field reported with ops=5 (read+subscribe) must not become a Number
    entity — this is the exact shape TPMS pressure/shunt SOC reported."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        side_effect=[
            {"sps": [{"name": "tp_state_1", "type": 7, "ref": "tpms_state"}]},
            {"sps": [{"name": "pressure", "type": 3, "ops": 5, "unit": "kPa"}]},
        ]
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("456", "tpms")

    pressure = next(f for f in fields if f.name == "tp_state_1.pressure")
    assert pressure.writable is False
    assert pressure.readable is True
    assert pressure.subscribable is True


async def test_tank_ratio_and_connected_are_sensors_with_real_schema() -> None:
    """Real-world regression: tank fill-level (ai_N.ratio) and connectivity
    (ai_N.connected) were showing up as Configuration/missing instead of
    sensors. Confirmed via a real capture (captures/*.har in the sibling
    renogy-gateway repo) that analog_input_r.ratio reports ops=[2,4,5,7] —
    no literal write bit — same shape as the TPMS/inverter fields the
    ops=7 fix (v0.2.7) already covers. Locks in that fix for tanks too,
    using the exact captured schema."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {"name": "ratio", "type": 2, "ops": [2, 4, 5, 7], "unit": "%", "min": 0, "max": 100},
                {
                    "name": "mode",
                    "type": 2,
                    "ops": [1, 2, 4, 5],
                    "options": [
                        {"key": 1, "value": "2 Lines"},
                        {"key": 2, "value": "5 Lines"},
                        {"key": 3, "value": "comworks"},
                    ],
                },
                {"name": "connected", "type": 1, "ops": [2, 4, 5, 7]},
                {
                    "name": "alarm_lower_threshold",
                    "type": 2,
                    "ops": [1, 2, 4, 5, 7],
                    "unit": "%",
                    "min": -1,
                    "max": 101,
                },
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "analog_input_r")

    by_name = {f.name: f for f in fields}
    assert by_name["ratio"].writable is False  # -> sensor.py's RenogySensor
    assert by_name["connected"].writable is False  # -> binary_sensor.py
    assert by_name["mode"].writable is True  # genuine setting -> select.py
    assert by_name["alarm_lower_threshold"].writable is True  # -> number.py


async def test_tpms_readings_force_readonly_even_with_full_ops() -> None:
    """Real-world regression: on some rigs the schema marks TPMS pressure,
    online, and the tyre-status enum (leaf 'state') with ops=7 (the full
    write+read+subscribe bitmask) despite PROTOCOL.md §6 documenting
    tpms.tp_state_N.{pressure,temperature,battery_status,online,state} as
    pure readings. The ops=5 fix alone doesn't cover this — these need an
    explicit, namespace-scoped override (see _FORCE_READONLY_LEAVES_BY_NAMESPACE)."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        side_effect=[
            {"sps": [{"name": "tp_state_1", "type": 7, "ref": "tpms_state"}]},
            {
                "sps": [
                    {"name": "pressure", "type": 3, "ops": 7, "unit": "kPa"},
                    {"name": "online", "type": 1, "ops": 7},
                    {
                        "name": "state",
                        "type": 2,
                        "ops": 7,
                        "options": [{"key": 0, "value": "Normal"}],
                    },
                ]
            },
        ]
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("456", "tpms")

    by_name = {f.name: f for f in fields}
    assert by_name["tp_state_1.pressure"].writable is False
    assert by_name["tp_state_1.online"].writable is False
    assert by_name["tp_state_1.state"].writable is False


async def test_distribution_box_state_leaf_unaffected_by_tpms_override() -> None:
    """The tpms-scoped 'state' override must not leak into other namespaces —
    distribution_box channel '.state' is the real writable on/off control.

    ops is the real PROTOCOL.md §7.4 example for dc_output_ext.state: the
    literal write code 1 must be present alongside 5/7 for writable to be
    True — see _parse_ops's docstring for why a bare "7" alone wouldn't do.
    """
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [{"name": "dc_10a_1.state", "type": 1, "ops": [1, 2, 4, 5, 7]}]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "distribution_box")

    assert fields[0].writable is True


async def test_force_readonly_leaf_match_is_case_insensitive() -> None:
    """Real-world capture (captures/*.har in the sibling renogy-gateway repo):
    the same inverter reports both lowercase "voltage" and capitalised
    "battery_input.Voltage" for equivalent quantities — an exact-case-only
    match misses the latter, which is why it showed up as a duplicate,
    unconverted entity instead of being treated the same as "voltage"."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={"sps": [{"name": "Voltage", "type": 3, "ops": 7, "unit": "V"}]}
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "battery_input")

    assert fields[0].writable is False


async def test_inverter_today_counters_force_readonly() -> None:
    """Confirmed live in captures/*.har: the inverter_history model's
    lowercase "_today" daily accumulators report ops=[1,2,4,5,7] — the
    literal write bit genuinely present — despite being counters no one
    would ever set (bat_chg_ah_today, generat_energy_today, etc.)."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {"name": "bat_chg_ah_today", "type": 2, "ops": [1, 2, 4, 5, 7]},
                {"name": "generat_energy_today", "type": 3, "ops": [1, 2, 4, 5, 7]},
                {"name": "Bat_Chg_Energy", "type": 2, "ops": [2, 4, 5, 7]},
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "inverter_history")

    by_name = {f.name: f for f in fields}
    assert by_name["bat_chg_ah_today"].writable is False
    assert by_name["generat_energy_today"].writable is False
    assert by_name["Bat_Chg_Energy"].writable is False  # already correct (no literal 1)


async def test_inverter_ac_input_readings_force_readonly() -> None:
    """packages/core/src/registry.ts hardcodes ac_input.AC_input_Voltage /
    AC_input_current as a fallback for this exact inverter model (RIV1230RCH
    -24S) because no capture ever shows gwm.get_model called for ac_input —
    the dashboard's own human-curated labels ("AC input voltage", "AC input
    current") confirm these are pure readings."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {"name": "AC_input_Voltage", "type": 3, "ops": 7, "unit": "V"},
                {"name": "AC_input_current", "type": 3, "ops": 7, "unit": "A"},
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "ac_input")

    by_name = {f.name: f for f in fields}
    assert by_name["AC_input_Voltage"].writable is False
    assert by_name["AC_input_current"].writable is False


async def test_get_fields_ref_cycle_guard() -> None:
    """A self-referencing model does not recurse forever."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [{"name": "child", "type": 7, "ref": "self_ref"}],
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "self_ref")

    assert fields == []


async def test_hide_leaves_excluded_from_fields() -> None:
    """Maintenance/protocol leaves are dropped even though schema-writable."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {"name": "save_config", "type": 1, "ops": 7},
                {"name": "max_current", "type": 2, "ops": 7, "min": 0, "max": 60},
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "charger")

    assert {f.name for f in fields} == {"max_current"}


async def test_distribution_box_channel_counts_excluded() -> None:
    """Schema-internal channel-count bookkeeping (confirmed via
    captures/*.har: dc_10a_count, dc_20a_count, etc.) isn't user-meaningful
    telemetry and shouldn't become a sensor entity."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {"name": "dc_10a_count", "type": 2, "ops": [2]},
                {"name": "dc_20a_count", "type": 2, "ops": [2]},
                {"name": "ai_count", "type": 2, "ops": [2]},
                {"name": "dc_input_voltage", "type": 3, "ops": [2, 4, 5, 7], "unit": "V"},
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "distribution_box")

    assert {f.name for f in fields} == {"dc_input_voltage"}


def test_skip_namespaces_matches_dashboard_curation() -> None:
    """Namespaces with real telemetry/settings in the dashboard must not be
    dropped wholesale, even though they're config-ish; only protocol/system
    internals neither app surfaces are skipped (see params.ts PARAM_HIDE_NS /
    bridge.ts SKIP_SUBSCRIBE_NS in the sibling renogy-gateway repo)."""
    not_skipped = {
        "gwmConfig",
        "digital_input",
        "signal",
        "alternator",
        "battery_temp_sensor",
        "inverter_history",
    }
    assert not (not_skipped & _SKIP_NAMESPACES)

    still_skipped = {
        "thing",
        "gwm",
        "version_ctrl",
        "driving_mode",
        "cloud",
        "customAlarm",
        "scene",
        "charger_history",
        "userdata_str",
    }
    assert still_skipped <= _SKIP_NAMESPACES


async def test_gwm_config_fields_resolved_via_get_fields() -> None:
    """gwmConfig is no longer skipped, so its fields resolve normally
    (e.g. socRule should be discoverable as a select-style enum field)."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [
                {
                    "name": "socRule",
                    "type": 2,
                    "ops": 7,
                    "options": [{"key": 0, "value": "Low"}, {"key": 1, "value": "Medium"}],
                },
            ]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "gwmConfig")

    assert {f.name for f in fields} == {"socRule"}


async def test_ctrl_sp_blacklist_parses_json_array() -> None:
    """ctrl_sp_blacklist is read and parsed into a set of relative paths."""
    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=json.dumps(["charger.max_current"]))

    discovery = RenogyDiscovery(rtm)
    blacklist = await discovery._get_ctrl_sp_blacklist("123")

    assert blacklist == frozenset({"charger.max_current"})


async def test_ctrl_sp_blacklist_empty_on_read_failure() -> None:
    """An RTM read failure for the blacklist yields an empty set, not a raise."""
    rtm = MagicMock()
    rtm.read = AsyncMock(side_effect=RenogyRTMError("boom"))

    discovery = RenogyDiscovery(rtm)
    blacklist = await discovery._get_ctrl_sp_blacklist("123")

    assert blacklist == frozenset()


async def test_ctrl_sp_blacklist_empty_on_malformed_value() -> None:
    """A non-list value (or invalid JSON) yields an empty set."""
    rtm = MagicMock()
    rtm.read = AsyncMock(return_value="not json at all {{{{")

    discovery = RenogyDiscovery(rtm)
    blacklist = await discovery._get_ctrl_sp_blacklist("123")

    assert blacklist == frozenset()


async def test_get_product_returns_namespaces_and_protocol() -> None:
    """get_product's 'protocol' (e.g. 'wifi') is connection-type metadata,
    not a telemetry field — confirmed live for Vision (pid 002C0000) via
    captures/*.har in the sibling renogy-gateway repo."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "models": ["thing", "version_ctrl"],
            "protocol": "wifi",
            "text": "Vision",
        }
    )

    discovery = RenogyDiscovery(rtm)
    namespaces, protocol = await discovery._get_product("002C0000")

    assert namespaces == ["thing", "version_ctrl"]
    assert protocol == "wifi"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (11005003, "V11.5.3"),
        (1005003, "V1.5.3"),
        (0, None),
        (-1, None),
    ],
)
async def test_get_firmware_decodes_packed_version(raw: int, expected: str | None) -> None:
    """sw_ver is packed as 2-3-3 digit groups — mirrors
    apps/dashboard/src/worker/bridge.ts's formatFirmware in the sibling
    renogy-gateway repo."""
    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=raw)

    discovery = RenogyDiscovery(rtm)
    assert await discovery._get_firmware("123") == expected


async def test_get_firmware_none_on_read_failure() -> None:
    """An RTM read failure is best-effort — returns None, doesn't raise."""
    rtm = MagicMock()
    rtm.read = AsyncMock(side_effect=RenogyRTMError("boom"))

    discovery = RenogyDiscovery(rtm)
    assert await discovery._get_firmware("123") is None


async def test_rpc_with_retry_succeeds_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dropped RPC (RenogyRTMError, not just a timeout) is retried and can
    still succeed — a single lost frame in the connect-time burst must not
    permanently fail discovery for that namespace."""
    monkeypatch.setattr(
        "custom_components.renogy_gateway.api.discovery.asyncio.sleep", AsyncMock()
    )
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        side_effect=[RenogyRTMError("dropped"), {"sps": [], "inherit": None}]
    )

    discovery = RenogyDiscovery(rtm)
    result = await discovery._get_model("shunt")

    assert result == []
    assert rtm.rpc.await_count == 2


async def test_rpc_with_retry_raises_after_exhausting_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A permanent failure still degrades gracefully (get_model caches []
    after retries are exhausted, doesn't propagate)."""
    monkeypatch.setattr(
        "custom_components.renogy_gateway.api.discovery.asyncio.sleep", AsyncMock()
    )
    rtm = MagicMock()
    rtm.rpc = AsyncMock(side_effect=RenogyRTMError("permanently dropped"))

    discovery = RenogyDiscovery(rtm)
    result = await discovery._get_model("shunt")

    assert result == []
    assert rtm.rpc.await_count == 3  # exhausted all retry attempts


async def test_get_devices_prepends_gateway_deduped() -> None:
    """The gwm.devs step-1 registration response carries the gateway's own
    device entry — it must be prepended to the child device list so the ONE
    Core surfaces as a device, without duplicating it if the child list also
    happens to include it."""
    gateway_entry = {"did_str": "111", "pid": "GW_PID", "text": "ONE Core"}
    child_entry = {"did_str": "222", "pid": "CHILD_PID", "text": "Shunt"}

    async def rpc(sp: str, data: dict) -> dict:
        if "dids" in data:
            return {"devs": [gateway_entry]}
        return {"devs": [child_entry]}

    rtm = MagicMock()
    rtm.rpc = AsyncMock(side_effect=rpc)

    discovery = RenogyDiscovery(rtm)
    devices = await discovery._get_devices("111")

    assert devices == [gateway_entry, child_entry]


async def test_get_devices_does_not_duplicate_gateway_in_child_list() -> None:
    """If the child list also happens to include the gateway, it must not
    appear twice."""
    gateway_entry = {"did_str": "111", "pid": "GW_PID", "text": "ONE Core"}
    child_entry = {"did_str": "222", "pid": "CHILD_PID", "text": "Shunt"}

    async def rpc(sp: str, data: dict) -> dict:
        if "dids" in data:
            return {"devs": [gateway_entry]}
        return {"devs": [gateway_entry, child_entry]}

    rtm = MagicMock()
    rtm.rpc = AsyncMock(side_effect=rpc)

    discovery = RenogyDiscovery(rtm)
    devices = await discovery._get_devices("111")

    assert devices == [gateway_entry, child_entry]


async def test_metadata_only_device_still_resolves() -> None:
    """Real-world regression: "Vision" has only thing + version_ctrl
    namespaces, both always namespace-skipped, so it resolves to zero
    fields — but the device itself (with protocol/sw_version) must still
    be returned, not dropped, so __init__.py can register it as an HA
    device even with no entities."""
    rtm = MagicMock()

    async def rpc(sp: str, data: dict) -> dict:
        if "get_product" in sp:
            return {"models": ["thing", "version_ctrl"], "protocol": "wifi"}
        return {"sps": []}

    rtm.rpc = AsyncMock(side_effect=rpc)
    rtm.read = AsyncMock(return_value=11005003)  # thing.sw_ver

    discovery = RenogyDiscovery(rtm)
    device = await discovery._resolve_device(
        {"did_str": "4646428229905819205", "pid": "002C0000", "text": "Vision", "online": True}
    )

    assert device is not None
    assert device.fields == []
    assert device.protocol == "wifi"
    assert device.sw_version == "V11.5.3"


async def test_get_model_dedupes_concurrent_calls_for_same_namespace() -> None:
    """Two devices resolving concurrently and sharing a namespace must issue
    at most one gwm.get_model RPC for it, not one per caller."""
    rtm = MagicMock()
    call_count = 0

    async def rpc(sp: str, data: dict) -> dict:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0)  # yield so both concurrent callers overlap
        return {"sps": [{"name": "voltage", "type": 3, "ops": [2]}]}

    rtm.rpc = AsyncMock(side_effect=rpc)
    discovery = RenogyDiscovery(rtm)

    results = await asyncio.gather(
        discovery._get_model("shunt"), discovery._get_model("shunt")
    )

    assert call_count == 1
    assert results[0] == results[1]
    # A later call still hits the cache, not a fresh RPC.
    assert await discovery._get_model("shunt") == results[0]
    assert call_count == 1
