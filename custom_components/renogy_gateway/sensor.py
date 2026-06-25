"""Sensor platform for Renogy Gateway — read-only numeric telemetry."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import FieldSpec, RenogyDevice
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity

PARALLEL_UPDATES = 0

# Renogy unit string → (HA unit, SensorDeviceClass)
_UNIT_MAP: dict[str, tuple[str, SensorDeviceClass | None]] = {
    "W": (UnitOfPower.WATT, SensorDeviceClass.POWER),
    "kW": (UnitOfPower.KILO_WATT, SensorDeviceClass.POWER),
    "V": (UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE),
    "A": (UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT),
    "kWh": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
    "Wh": (UnitOfEnergy.WATT_HOUR, SensorDeviceClass.ENERGY),
    "°C": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    "℃": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    "kPa": (UnitOfPressure.KPA, SensorDeviceClass.PRESSURE),
}


def _is_sensor(field: FieldSpec) -> bool:
    """Return True if this field should be a plain numeric sensor entity."""
    # Read-only numeric with a unit, or read-only int/float without unit.
    # Enum-valued readings (options present) become a RenogyEnumSensor instead.
    return (
        not field.writable
        and field.field_type in (2, 3)  # int or float
        and not field.options
    )


def _is_enum_sensor(field: FieldSpec) -> bool:
    """Return True if this field is a read-only enum reading (status/mode code).

    Writable enum fields become select entities (select.py); a read-only enum
    has no writable counterpart there, so without this it matches none of the
    platform filters and is silently dropped.
    """
    return not field.writable and bool(field.options)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Renogy sensor entities from a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data
    entities: list[RenogySensor | RenogyEnumSensor] = []
    for device in coordinator.devices.values():
        for field in device.fields:
            if _is_sensor(field):
                entities.append(RenogySensor(coordinator, device, field))
            elif _is_enum_sensor(field):
                entities.append(RenogyEnumSensor(coordinator, device, field))
    async_add_entities(entities)


class RenogySensor(RenogyBaseEntity, SensorEntity):
    """A read-only numeric sensor entity from Renogy telemetry."""

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
    ) -> None:
        """Initialize the sensor entity with unit and device class from the field spec."""
        super().__init__(coordinator, device, field)
        unit_entry = _UNIT_MAP.get(field.unit or "")
        if unit_entry:
            self._attr_native_unit_of_measurement = unit_entry[0]
            self._attr_device_class = unit_entry[1]
        elif field.unit:
            self._attr_native_unit_of_measurement = field.unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = field.precision or None

    @property
    def native_value(self) -> float | int | None:
        """Return the latest telemetry value."""
        return self._value


class RenogyEnumSensor(RenogyBaseEntity, SensorEntity):
    """A read-only enum reading (status/mode code) from Renogy telemetry."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
    ) -> None:
        """Initialize the enum sensor and build the key→label option map."""
        super().__init__(coordinator, device, field)
        assert field.options is not None
        self._key_to_label: dict[str, str] = {
            str(opt["key"]): str(opt["value"]) for opt in field.options
        }
        self._attr_options = list(self._key_to_label.values())

    @property
    def native_value(self) -> str | None:
        """Return the current option's display label."""
        if self._value is None:
            return None
        return self._key_to_label.get(str(self._value))
