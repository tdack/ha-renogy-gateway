"""Tests for the Renogy Gateway switch platform."""

from unittest.mock import MagicMock

from custom_components.renogy_gateway.api.models import FieldSpec, RenogyDevice
from custom_components.renogy_gateway.switch import (
    RenogySwitch,
    _is_config_switch,
    _is_load_switch,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .conftest import FIELD_RELAY, MOCK_BOX_DEVICE


async def test_switch_turn_on_writes_true(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Turn on calls coordinator.async_write with True."""
    switch = RenogySwitch(mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY)
    switch.hass = hass

    await switch.async_turn_on()
    mock_coordinator.async_write.assert_awaited_once_with(FIELD_RELAY.sp, True)


async def test_switch_turn_off_writes_false(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Turn off calls coordinator.async_write with False."""
    switch = RenogySwitch(mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY)
    switch.hass = hass

    await switch.async_turn_off()
    mock_coordinator.async_write.assert_awaited_once_with(FIELD_RELAY.sp, False)


async def test_switch_state_from_telemetry(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Switch is_on reflects telemetry push."""
    switch = RenogySwitch(mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY)
    switch.hass = hass
    switch.async_write_ha_state = MagicMock()

    assert switch.is_on is None

    switch._handle_telemetry(True)
    assert switch.is_on is True

    switch._handle_telemetry(False)
    assert switch.is_on is False


async def test_switch_has_user_label(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Switch name comes from user-assigned label."""
    switch = RenogySwitch(mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY)
    assert switch.name == "Cooling Fan"


async def test_switch_seeds_value_from_coordinator_cache(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """A cached live value from the coordinator seeds is_on immediately."""
    mock_coordinator.get_value.return_value = True
    switch = RenogySwitch(mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY)
    switch.hass = hass
    switch.entity_id = "switch.test_relay"
    switch.async_write_ha_state = MagicMock()

    await switch.async_added_to_hass()
    assert switch.is_on is True


def test_relay_without_measurement_sibling_is_config_switch() -> None:
    """A writable bool with no power/current/voltage sibling is a config toggle."""
    assert _is_load_switch(FIELD_RELAY, MOCK_BOX_DEVICE) is False
    assert _is_config_switch(FIELD_RELAY, MOCK_BOX_DEVICE) is True


def test_relay_with_power_sibling_is_load_switch() -> None:
    """A writable bool with a power sibling is a real load — primary control."""
    power_field = FieldSpec(
        sp="4623589794012005944/distribution_box.relay_3.power",
        name="relay_3.power",
        field_type=3,
        ops=6,  # read + subscribe
    )
    device = RenogyDevice(
        did_str=MOCK_BOX_DEVICE.did_str,
        pid=MOCK_BOX_DEVICE.pid,
        sku=MOCK_BOX_DEVICE.sku,
        name=MOCK_BOX_DEVICE.name,
        online=True,
        fields=[*MOCK_BOX_DEVICE.fields, power_field],
    )
    relay_field = next(f for f in device.fields if f.sp == FIELD_RELAY.sp)

    assert _is_load_switch(relay_field, device) is True
    assert _is_config_switch(relay_field, device) is False


async def test_config_switch_entity_has_config_category(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """A switch built with is_config=True is tagged EntityCategory.CONFIG."""
    switch = RenogySwitch(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY, is_config=True
    )
    assert switch.entity_category == EntityCategory.CONFIG


async def test_load_switch_entity_has_no_category(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """A switch built without is_config has no entity category (primary control)."""
    switch = RenogySwitch(mock_coordinator, MOCK_BOX_DEVICE, FIELD_RELAY)
    assert switch.entity_category is None
