"""Tests for the Renogy Gateway sensor platform."""

from unittest.mock import MagicMock

from custom_components.renogy_gateway.sensor import RenogySensor
from homeassistant.core import HomeAssistant

from .conftest import FIELD_SOC, MOCK_SHUNT_DEVICE


async def test_sensor_state_from_telemetry(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Sensor native_value updates when a telemetry push arrives."""
    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, FIELD_SOC)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()

    assert sensor.native_value is None

    sensor._handle_telemetry(87.5)
    assert sensor.native_value == 87.5
    sensor.async_write_ha_state.assert_called_once()


async def test_sensor_unavailable_on_rtm_disconnect(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Sensor becomes unavailable when RTM disconnects."""
    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, FIELD_SOC)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()

    sensor._handle_telemetry(90.0)
    assert sensor.available is True

    sensor._handle_availability(False)
    assert sensor.available is False


async def test_sensor_unit_and_device_class(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """SOC sensor has percentage unit and correct device class."""

    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, FIELD_SOC)
    assert sensor.native_unit_of_measurement == "%"
    # % is not in _UNIT_MAP so no device class — it falls through to raw unit
    assert sensor.device_class is None


async def test_sensor_unique_id(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Sensor has a stable unique ID."""
    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, FIELD_SOC)
    assert sensor.unique_id == f"renogy_{FIELD_SOC.sp}"
