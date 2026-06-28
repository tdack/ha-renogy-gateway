"""Tests for the Renogy Gateway coordinator."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.renogy_gateway.api.models import FieldSpec, RenogyDevice
from custom_components.renogy_gateway.coordinator import RenogyCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import MOCK_BOX_DEVICE, MOCK_CHARGER_DEVICE, FIELD_CHARGE_VOLTAGE


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
        await coordinator.async_write(
            f"{device.did_str}/distribution_box.relay_3.state", True
        )
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

    await coordinator.async_write(
        f"{MOCK_BOX_DEVICE.did_str}/distribution_box.relay_3.state", True
    )
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


async def test_drop_phantom_instances_removes_dead_slots(
    hass: HomeAssistant,
    mock_config_entry,
) -> None:
    """Instance slots with no live seeded value are dropped; live ones and non-instance fields are kept."""
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
        fields=[FieldSpec(sp="123/shunt.main_battery_soc", name="main_battery_soc", field_type=3, ops=6)],
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
            did_str="123", pid="old-pid", sku="s", name="n", online=True, fields=[old_field]
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
    monkeypatch.setattr(
        "custom_components.renogy_gateway.coordinator.RTM_RECONNECT_DELAY_MIN", 0
    )

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
