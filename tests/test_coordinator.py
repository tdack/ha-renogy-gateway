"""Tests for the Renogy Gateway coordinator."""

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
