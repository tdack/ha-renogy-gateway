"""Tests for the Renogy Gateway discovery module."""

import json
from unittest.mock import AsyncMock, MagicMock

from custom_components.renogy_gateway.api.discovery import (
    _SKIP_NAMESPACES,
    RenogyDiscovery,
    _apply_labels,
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
    """userdata_str.config is double-encoded JSON — must parse twice."""
    inner_dict = {"dc_10a_1": "Bedroom Light", "relay_3": "Cooling Fan"}
    inner_str = json.dumps(inner_dict)
    outer_str = json.dumps(inner_str)

    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=outer_str)

    discovery = RenogyDiscovery(rtm)
    labels = await discovery._get_user_labels("123")
    assert labels == inner_dict


async def test_user_label_already_single_parsed() -> None:
    """If data is already a dict (single parse), handle gracefully."""
    inner_dict = {"dc_10a_1": "Bedroom Light"}

    rtm = MagicMock()
    rtm.read = AsyncMock(return_value=inner_dict)

    discovery = RenogyDiscovery(rtm)
    labels = await discovery._get_user_labels("123")
    assert labels == inner_dict


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


async def test_known_telemetry_paths_forced_readonly() -> None:
    """Fields documented as pure telemetry (PROTOCOL.md §6/§7.4) must not
    surface as Number/Select entities even when the schema marks them
    writable. Covers a real-world regression: TPMS pressure and shunt SOC
    were showing up as Configuration items instead of sensors."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        side_effect=[
            {"sps": [{"name": "main_battery_soc", "type": 3, "ops": 7, "unit": "%"}]},
            {
                "sps": [
                    {"name": "tp_state_1", "type": 7, "ref": "tpms_state"},
                ]
            },
            {
                "sps": [
                    {"name": "pressure", "type": 3, "ops": 7, "unit": "kPa"},
                ]
            },
        ]
    )

    discovery = RenogyDiscovery(rtm)
    shunt_fields = await discovery._get_fields("123", "shunt")
    tpms_fields = await discovery._get_fields("456", "tpms")

    by_name = {f.name: f for f in shunt_fields + tpms_fields}
    assert by_name["main_battery_soc"].writable is False
    assert by_name["tp_state_1.pressure"].writable is False


async def test_tank_ratio_forced_readonly() -> None:
    """ai_N.ratio (tank fill level) is documented read-only (PROTOCOL.md
    §7.4) but some rigs' schemas mark it writable anyway."""
    rtm = MagicMock()
    rtm.rpc = AsyncMock(
        return_value={
            "sps": [{"name": "ai_1.ratio", "type": 2, "ops": 7, "unit": "%"}]
        }
    )

    discovery = RenogyDiscovery(rtm)
    fields = await discovery._get_fields("123", "distribution_box")

    assert fields[0].writable is False


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
