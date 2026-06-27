"""Sensor platform for Renogy Gateway — read-only numeric telemetry."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import FieldSpec, RenogyDevice
from .const import DOMAIN, is_diagnostic_field
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity

PARALLEL_UPDATES = 0

# Renogy unit string → (HA unit, SensorDeviceClass, scale to convert the raw
# wire value into that HA unit). Milli-prefixed units exist on some devices
# (e.g. an inverter reporting AC input current in "mA") alongside other
# fields already in "A" — scale them down so every entity of a given
# device_class shares one consistent base unit instead of mixing prefixes.
_UNIT_MAP: dict[str, tuple[str, SensorDeviceClass | None, float]] = {
    "W": (UnitOfPower.WATT, SensorDeviceClass.POWER, 1.0),
    "kW": (UnitOfPower.KILO_WATT, SensorDeviceClass.POWER, 1.0),
    "mW": (UnitOfPower.WATT, SensorDeviceClass.POWER, 0.001),
    "V": (UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, 1.0),
    "mV": (UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, 0.001),
    "A": (UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 1.0),
    "mA": (UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 0.001),
    # Chinese unit string seen on some fields (e.g. charger.max_current,
    # confirmed via captures/*.har) — matches packages/core/src/params.ts's
    # UNIT_MAP translation in the sibling renogy-gateway repo.
    "安培": (UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, 1.0),
    "kWh": (UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, 1.0),
    "Wh": (UnitOfEnergy.WATT_HOUR, SensorDeviceClass.ENERGY, 1.0),
    "°C": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, 1.0),
    "℃": (UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, 1.0),
    "kPa": (UnitOfPressure.KPA, SensorDeviceClass.PRESSURE, 1.0),
}

# Decimal places to show when the schema doesn't specify a usable precision
# (0 or absent) for a float-valued field. Integer fields never get a display
# precision — there's nothing to round.
_DEFAULT_FLOAT_PRECISION = 2


def _display_precision(field: FieldSpec) -> int | None:
    """Decimal places to show, capped at 2 (e.g. 14.349999 -> 14.35)."""
    if field.field_type != 3:  # only floats need rounding
        return None
    return min(field.precision, _DEFAULT_FLOAT_PRECISION) if field.precision else _DEFAULT_FLOAT_PRECISION


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
    entities: list[RenogySensor | RenogyEnumSensor | RenogyConnectionTypeSensor] = []
    for device in coordinator.devices.values():
        for field in device.fields:
            if _is_sensor(field):
                entities.append(RenogySensor(coordinator, device, field))
            elif _is_enum_sensor(field):
                entities.append(RenogyEnumSensor(coordinator, device, field))
        if device.protocol:
            entities.append(RenogyConnectionTypeSensor(device))
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
        self._scale = 1.0
        unit_entry = _UNIT_MAP.get(field.unit or "")
        if unit_entry:
            self._attr_native_unit_of_measurement = unit_entry[0]
            self._attr_device_class = unit_entry[1]
            self._scale = unit_entry[2]
        elif field.unit:
            self._attr_native_unit_of_measurement = field.unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_suggested_display_precision = _display_precision(field)
        if is_diagnostic_field(field.sp):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> float | int | None:
        """Return the latest telemetry value, scaled to the displayed unit."""
        if self._value is None:
            return None
        if self._scale == 1.0:
            return self._value
        try:
            return float(self._value) * self._scale
        except (TypeError, ValueError):
            return None


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
        if is_diagnostic_field(field.sp):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the current option's display label."""
        if self._value is None:
            return None
        return self._key_to_label.get(str(self._value))


class RenogyConnectionTypeSensor(SensorEntity):
    """Static connection-type info (e.g. 'wifi', 'BLE RS485') from gwm.get_product.

    Not tied to a telemetry field — `protocol` is read once at discovery and
    never changes, so there's nothing to subscribe to. Exists mainly so
    metadata-only devices (e.g. "Vision" — thing + version_ctrl, both always
    namespace-skipped) get at least one entity: HA only creates a device
    record implicitly via an entity's device_info, so a device with zero
    fields would otherwise never appear at all (see __init__.py for the
    explicit device-registry registration that also covers this).
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device: RenogyDevice) -> None:
        """Initialize with the device's static protocol string."""
        self._attr_unique_id = f"renogy_{device.did_str}_protocol"
        self._attr_name = "Connection type"
        self._attr_native_value = device.protocol
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.did_str)},
            name=device.name,
            manufacturer="Renogy",
            model=device.sku,
            sw_version=device.sw_version,
        )

    @property
    def available(self) -> bool:
        """Always available — this is static metadata, not live telemetry."""
        return True
