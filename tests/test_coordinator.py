"""Tests for the Renogy Gateway coordinator."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from custom_components.renogy_gateway.api.models import FieldSpec, RenogyDevice
from custom_components.renogy_gateway.coordinator import RenogyCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .conftest import MOCK_BOX_DEVICE


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
