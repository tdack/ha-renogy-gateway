"""Tests for the Renogy Gateway coordinator."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.renogy_gateway.api.models import FieldSpec, RenogyDevice
from custom_components.renogy_gateway.coordinator import RenogyCoordinator

from .conftest import FIELD_CHARGE_VOLTAGE, MOCK_BOX_DEVICE, MOCK_CHARGER_DEVICE


async def test_async_write_rejects_blacklisted_sp(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """A write to a blacklisted field raises and never reaches the RTM."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    device = RenogyDevice(
        did_str=MOCK_BOX_DEVICE.did_str,
        pid=MOCK_BOX_DEVICE.pid,
        sku=MOCK_BOX_DEVICE.sku,
        name=MOCK_BOX_DEVICE.name,
        online=True,
        fields=MOCK_BOX_DEVICE.fields,
        ctrl_sp_blacklist=frozenset({"distribution_box.relay_3.state"}),
    )
    coordinator.devices = {device.did_str: device}
    coordinator._rtm.write = AsyncMock()

    with pytest.raises(HomeAssistantError):
        await coordinator.async_write(f"{device.did_str}/distribution_box.relay_3.state", True)
    coordinator._rtm.write.assert_not_awaited()


async def test_async_write_allows_non_blacklisted_sp(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """A write to a field outside the blacklist proceeds normally."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {MOCK_BOX_DEVICE.did_str: MOCK_BOX_DEVICE}
    coordinator._rtm.write = AsyncMock(return_value={"code": 0})

    await coordinator.async_write(f"{MOCK_BOX_DEVICE.did_str}/distribution_box.relay_3.state", True)
    coordinator._rtm.write.assert_awaited_once()


async def test_async_write_rejects_unknown_sp(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Writing to an sp with no matching FieldSpec raises before any RTM frame."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {MOCK_BOX_DEVICE.did_str: MOCK_BOX_DEVICE}
    coordinator._rtm.write = AsyncMock()

    with pytest.raises(HomeAssistantError, match="Unknown sp"):
        await coordinator.async_write(f"{MOCK_BOX_DEVICE.did_str}/no.such.field", True)
    coordinator._rtm.write.assert_not_awaited()


async def test_async_write_rejects_non_writable_field(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Writing to a field the schema marks read-only raises before any RTM frame."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    readonly_field = FieldSpec(
        sp=f"{MOCK_BOX_DEVICE.did_str}/thing.online", name="online", field_type=1, ops=6
    )
    device = RenogyDevice(
        did_str=MOCK_BOX_DEVICE.did_str,
        pid=MOCK_BOX_DEVICE.pid,
        sku=MOCK_BOX_DEVICE.sku,
        name=MOCK_BOX_DEVICE.name,
        online=True,
        fields=[readonly_field],
    )
    coordinator.devices = {device.did_str: device}
    coordinator._rtm.write = AsyncMock()

    with pytest.raises(HomeAssistantError, match="not writable"):
        await coordinator.async_write(readonly_field.sp, True)
    coordinator._rtm.write.assert_not_awaited()


async def test_async_write_rejects_wrong_type(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Writing a string to a boolean field raises before any RTM frame."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {MOCK_BOX_DEVICE.did_str: MOCK_BOX_DEVICE}
    coordinator._rtm.write = AsyncMock()

    with pytest.raises(HomeAssistantError, match="expects boolean"):
        await coordinator.async_write(
            f"{MOCK_BOX_DEVICE.did_str}/distribution_box.relay_3.state", "on"
        )
    coordinator._rtm.write.assert_not_awaited()


async def test_async_write_rejects_out_of_range_value(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Writing a value outside the schema's min/max raises before any RTM frame."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {MOCK_CHARGER_DEVICE.did_str: MOCK_CHARGER_DEVICE}
    coordinator._rtm.write = AsyncMock()

    with pytest.raises(HomeAssistantError, match="below min"):
        await coordinator.async_write(FIELD_CHARGE_VOLTAGE.sp, 1.0)
    coordinator._rtm.write.assert_not_awaited()

    with pytest.raises(HomeAssistantError, match="above max"):
        await coordinator.async_write(FIELD_CHARGE_VOLTAGE.sp, 100.0)
    coordinator._rtm.write.assert_not_awaited()


async def test_async_write_allows_valid_value_within_bounds(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """A correctly-typed, in-range value still reaches the RTM unchanged."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {MOCK_CHARGER_DEVICE.did_str: MOCK_CHARGER_DEVICE}
    coordinator._rtm.write = AsyncMock(return_value={"code": 0})

    await coordinator.async_write(FIELD_CHARGE_VOLTAGE.sp, 13.5)

    coordinator._rtm.write.assert_awaited_once_with(FIELD_CHARGE_VOLTAGE.sp, 13.5)


def _writable_device(*fields: FieldSpec) -> RenogyDevice:
    return RenogyDevice(did_str="123", pid="p", sku="s", name="n", online=True, fields=list(fields))


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
async def test_async_write_rejects_non_finite_numbers(
    hass: HomeAssistant,
    mock_config_entry,
    bad: float,
) -> None:
    """NaN passes every bounds comparison and ±Infinity passes an unbounded
    field; neither may reach the gateway (json.dumps would emit a non-JSON token)."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    bounded = FieldSpec(
        sp="123/charger.v", name="v", field_type=3, ops=7, min_value=0.0, max_value=20.0
    )
    unbounded = FieldSpec(sp="123/charger.w", name="w", field_type=3, ops=7)
    coordinator.devices = {"123": _writable_device(bounded, unbounded)}
    coordinator._rtm.write = AsyncMock()

    for field in (bounded, unbounded):
        with pytest.raises(HomeAssistantError, match="finite"):
            await coordinator.async_write(field.sp, bad)
    coordinator._rtm.write.assert_not_awaited()


async def test_async_write_rejects_integer_beyond_safe_range(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """An unbounded integer field accepts only integers the canonical core
    (JS safe-integer range) would accept."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    field = FieldSpec(sp="123/charger.n", name="n", field_type=2, ops=7)
    coordinator.devices = {"123": _writable_device(field)}
    coordinator._rtm.write = AsyncMock(return_value={"code": 0})

    for bad in (10**300, 2**53, -(2**53)):
        with pytest.raises(HomeAssistantError, match="out-of-range"):
            await coordinator.async_write(field.sp, bad)
    coordinator._rtm.write.assert_not_awaited()

    await coordinator.async_write(field.sp, 2**53 - 1)
    coordinator._rtm.write.assert_awaited_once()


async def test_async_write_enforces_schema_options(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """An in-range value that isn't one of the schema's options is refused;
    a listed option passes."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    field = FieldSpec(
        sp="123/analog_input_r.ai_1.mode",
        name="ai_1.mode",
        field_type=2,
        ops=7,
        min_value=0.0,
        max_value=5.0,
        options=[{"key": 0, "value": "Off"}, {"key": 2, "value": "Fresh"}],
        schema_option_keys=frozenset({"0", "2"}),
    )
    coordinator.devices = {"123": _writable_device(field)}
    coordinator._rtm.write = AsyncMock(return_value={"code": 0})

    with pytest.raises(HomeAssistantError, match="not one of its options"):
        await coordinator.async_write(field.sp, 1)
    coordinator._rtm.write.assert_not_awaited()

    await coordinator.async_write(field.sp, 2)
    coordinator._rtm.write.assert_awaited_once_with(field.sp, 2)


async def test_async_write_ignores_curated_options_and_boolean_options(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Curated (non-schema) options don't gate writes, and booleans are exempt
    from option membership even when the schema lists keys for them."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    curated = FieldSpec(
        sp="123/charger.battery_type",
        name="battery_type",
        field_type=2,
        ops=7,
        options=[{"key": 0, "value": "User-defined"}],
    )
    boolean = FieldSpec(
        sp="123/relay.state",
        name="state",
        field_type=1,
        ops=7,
        options=[{"key": 0, "value": "Off"}, {"key": 1, "value": "On"}],
        schema_option_keys=frozenset({"0", "1"}),
    )
    coordinator.devices = {"123": _writable_device(curated, boolean)}
    coordinator._rtm.write = AsyncMock(return_value={"code": 0})

    await coordinator.async_write(curated.sp, 7)
    await coordinator.async_write(boolean.sp, True)
    assert coordinator._rtm.write.await_count == 2


async def test_drop_phantom_instances_removes_dead_slots(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Instance slots with no live seeded value are dropped.

    Live ones, and non-instance fields, are kept.
    """
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)

    dead_field = FieldSpec(
        sp="123/tpms.tp_state_1.pressure",
        name="tp_state_1.pressure",
        field_type=3,
        ops=6,
    )
    live_field = FieldSpec(
        sp="123/tpms.tp_state_2.pressure",
        name="tp_state_2.pressure",
        field_type=3,
        ops=6,
    )
    other_field = FieldSpec(
        sp="123/charger.max_current",
        name="max_current",
        field_type=2,
        ops=7,
    )
    device = RenogyDevice(
        did_str="123",
        pid="p",
        sku="s",
        name="n",
        online=True,
        fields=[dead_field, live_field, other_field],
    )
    coordinator.devices = {"123": device}
    coordinator._last_values = {live_field.sp: 101.0}

    coordinator._drop_phantom_instances()

    assert {f.sp for f in device.fields} == {live_field.sp, other_field.sp}


async def test_drop_phantom_instances_ignores_writable_setting_defaults(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Real-world regression: an unbound TPMS slot's settings (calibration
    pressure, alarm thresholds, axle_num, ...) answer with a stable firmware
    default even with no physical sensor paired, while the actual readings
    (pressure, online, ...) stay unset. Liveness must come from a reading,
    not a writable setting's default — otherwise every unbound slot looks
    live forever."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)

    unbound_reading = FieldSpec(
        sp="123/tpms.tp_state_3.pressure",
        name="tp_state_3.pressure",
        field_type=3,
        ops=6,  # read + subscribe, not writable (post ops-fix)
    )
    unbound_setting_with_default = FieldSpec(
        sp="123/tpms.tp_state_3.calibration_pressure",
        name="tp_state_3.calibration_pressure",
        field_type=3,
        ops=7,  # writable — answers with a firmware default regardless
    )
    bound_reading = FieldSpec(
        sp="123/tpms.tp_state_1.pressure",
        name="tp_state_1.pressure",
        field_type=3,
        ops=6,
    )
    device = RenogyDevice(
        did_str="123",
        pid="p",
        sku="s",
        name="n",
        online=True,
        fields=[unbound_reading, unbound_setting_with_default, bound_reading],
    )
    coordinator.devices = {"123": device}
    coordinator._last_values = {
        unbound_setting_with_default.sp: 430.0,  # default, even though unbound
        bound_reading.sp: 215.0,
    }

    coordinator._drop_phantom_instances()

    assert {f.sp for f in device.fields} == {bound_reading.sp}


async def test_merge_devices_keeps_prior_fields_on_empty_rediscovery(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """A device that rediscovers with zero fields (transient RPC drop) keeps
    its prior schema instead of having its entities torn down; live metadata
    (online, name) still refreshes from the fresh pass."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)

    prior_device = RenogyDevice(
        did_str="123",
        pid="shunt-pid",
        sku="s",
        name="Shunt 300A",
        online=True,
        fields=[
            FieldSpec(
                sp="123/shunt.main_battery_soc",
                name="main_battery_soc",
                field_type=3,
                ops=6,
            )
        ],
    )
    coordinator.devices = {"123": prior_device}

    fresh_device = RenogyDevice(
        did_str="123",
        pid="shunt-pid",
        sku="s",
        name="Shunt 300A (renamed)",
        online=False,
        fields=[],
    )

    merged = coordinator._merge_devices([fresh_device])

    assert merged["123"].fields == prior_device.fields
    assert merged["123"].online is False
    assert merged["123"].name == "Shunt 300A (renamed)"


async def test_merge_devices_uses_fresh_fields_when_present(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """A device that successfully rediscovers its fields is not merged with
    the prior snapshot — the fresh fields win."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)

    old_field = FieldSpec(sp="123/shunt.old", name="old", field_type=3, ops=6)
    new_field = FieldSpec(sp="123/shunt.new", name="new", field_type=3, ops=6)
    coordinator.devices = {
        "123": RenogyDevice(
            did_str="123", pid="p", sku="s", name="n", online=True, fields=[old_field]
        )
    }
    fresh_device = RenogyDevice(
        did_str="123", pid="p", sku="s", name="n", online=True, fields=[new_field]
    )

    merged = coordinator._merge_devices([fresh_device])

    assert merged["123"].fields == [new_field]


async def test_merge_devices_drops_genuinely_removed_device(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """A device absent from the fresh discovery entirely (actually removed)
    must not be resurrected from the prior snapshot."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.devices = {
        "123": RenogyDevice(did_str="123", pid="p", sku="s", name="n", online=True, fields=[])
    }

    merged = coordinator._merge_devices([])

    assert merged == {}


async def test_merge_devices_does_not_merge_across_pid_change(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """If the same did_str now reports a different pid, treat it as a new
    device rather than inheriting the old one's fields."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    old_field = FieldSpec(sp="123/shunt.old", name="old", field_type=3, ops=6)
    coordinator.devices = {
        "123": RenogyDevice(
            did_str="123",
            pid="old-pid",
            sku="s",
            name="n",
            online=True,
            fields=[old_field],
        )
    }
    fresh_device = RenogyDevice(
        did_str="123", pid="new-pid", sku="s", name="n", online=True, fields=[]
    )

    merged = coordinator._merge_devices([fresh_device])

    assert merged["123"].fields == []
    assert merged["123"].pid == "new-pid"


async def test_rtm_wired_to_schedule_reconnect(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """The coordinator must register itself as the RTM's unexpected-disconnect callback."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)

    assert coordinator._rtm._on_unexpected_disconnect == coordinator.schedule_reconnect


async def test_unexpected_disconnect_schedules_reconnect_and_marks_unavailable(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Firing the RTM's unexpected-disconnect callback schedules a reconnect and
    immediately fans out availability=False."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    availability_calls: list[bool] = []
    coordinator.register_availability_callback(availability_calls.append)
    coordinator._rtm.disconnect = AsyncMock()
    coordinator._connect_and_discover = AsyncMock(side_effect=asyncio.CancelledError)

    coordinator._rtm._on_unexpected_disconnect()
    await asyncio.sleep(0)  # let the scheduled background task run to its first await

    assert coordinator._reconnect_task is not None
    assert availability_calls == [False]


async def test_reconnect_success_marks_available(
    hass: HomeAssistant,
    mock_config_entry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful reconnect attempt fans out availability=True and clears the task."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    availability_calls: list[bool] = []
    coordinator.register_availability_callback(availability_calls.append)
    coordinator._rtm.disconnect = AsyncMock()
    coordinator._connect_and_discover = AsyncMock()
    monkeypatch.setattr("custom_components.renogy_gateway.coordinator.RTM_RECONNECT_DELAY_MIN", 0)

    coordinator.schedule_reconnect()
    await coordinator._reconnect_task

    assert availability_calls == [False, True]
    assert coordinator._reconnect_task is None


async def test_async_shutdown_does_not_schedule_reconnect(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Calling async_shutdown() must not leave a reconnect scheduled afterwards."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator._rtm.disconnect = AsyncMock()

    await coordinator.async_shutdown()
    coordinator._rtm._on_unexpected_disconnect()  # would-be late callback, e.g. from a stale reader
    await asyncio.sleep(0)

    assert coordinator._reconnect_task is None
