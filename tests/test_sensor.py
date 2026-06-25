"""Tests for the Renogy Gateway sensor platform."""

from unittest.mock import MagicMock

from custom_components.renogy_gateway.api.models import FieldSpec
from custom_components.renogy_gateway.sensor import (
    RenogyEnumSensor,
    RenogySensor,
    _is_enum_sensor,
    _is_sensor,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .conftest import FIELD_SOC, FIELD_SOC_RULE, FIELD_TPMS_STATE, MOCK_SHUNT_DEVICE, MOCK_TPMS_DEVICE


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


def test_is_sensor_excludes_enum_fields() -> None:
    """A read-only field with options is not a plain sensor — it's an enum sensor."""
    assert _is_sensor(FIELD_TPMS_STATE) is False
    assert _is_enum_sensor(FIELD_TPMS_STATE) is True


def test_is_enum_sensor_excludes_writable_fields() -> None:
    """A writable enum field is a select entity, not an enum sensor."""
    assert _is_enum_sensor(FIELD_SOC_RULE) is False


async def test_enum_sensor_native_value_maps_key_to_label(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Enum sensor resolves the raw telemetry key to its display label."""
    sensor = RenogyEnumSensor(mock_coordinator, MOCK_TPMS_DEVICE, FIELD_TPMS_STATE)
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()

    assert sensor.device_class == SensorDeviceClass.ENUM
    assert sensor.native_value is None

    sensor._handle_telemetry(1)
    assert sensor.native_value == "Low Pressure"


async def test_sensor_not_diagnostic_by_default(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Plain telemetry (e.g. battery SOC) is not tucked into Diagnostic."""
    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, FIELD_SOC)
    assert sensor.entity_category is None


async def test_sensor_diagnostic_for_status_like_field(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """A read-only field matching a diagnostic pattern (e.g. firmware
    version, protocol, alarm/fault/status) gets EntityCategory.DIAGNOSTIC."""
    firmware_field = FieldSpec(
        sp="4774953285866299397/version_ctrl.firmware_code",
        name="firmware_code",
        field_type=2,
        ops=6,
    )
    sensor = RenogySensor(mock_coordinator, MOCK_SHUNT_DEVICE, firmware_field)
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
