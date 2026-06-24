"""Number platform for Renogy Gateway — writable numeric configuration parameters."""

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import FieldSpec, RenogyDevice
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity
from .sensor import _UNIT_MAP

PARALLEL_UPDATES = 0


def _is_light_ratio(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this is a dimmable light's '.ratio' brightness field.

    Those are already exposed as brightness on the light entity (see
    light.py); a number entity would just duplicate the same control.
    """
    if not field.sp.endswith(".ratio"):
        return False
    state_sp = field.sp.rsplit(".", 1)[0] + ".state"
    return any(
        f.sp == state_sp and f.writable and f.field_type == 1 for f in device.fields
    )


def _is_number(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this field should be a number entity."""
    return (
        field.writable
        and field.field_type in (2, 3)  # int or float
        and not field.options  # not an enum
        and field.min_value is not None
        and field.max_value is not None
        and not _is_light_ratio(field, device)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Renogy number entities from a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data
    entities = [
        RenogyNumber(coordinator, device, field)
        for device in coordinator.devices.values()
        for field in device.fields
        if _is_number(field, device)
    ]
    async_add_entities(entities)


class RenogyNumber(RenogyBaseEntity, NumberEntity):
    """A writable numeric configuration parameter."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
    ) -> None:
        """Initialize number entity with range and unit from the field spec."""
        super().__init__(coordinator, device, field)
        self._attr_native_min_value = field.min_value or 0.0
        self._attr_native_max_value = field.max_value or 100.0
        self._attr_native_step = (
            10 ** (-field.precision) if field.precision > 0 else 1.0
        )
        unit_entry = _UNIT_MAP.get(field.unit or "")
        if unit_entry:
            self._attr_native_unit_of_measurement = unit_entry[0]
        elif field.unit:
            self._attr_native_unit_of_measurement = field.unit

    @property
    def native_value(self) -> float | None:
        """Return the current numeric value."""
        if self._value is None:
            return None
        try:
            return float(self._value)
        except TypeError, ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        """Write the new value to the field."""
        payload = int(value) if self._field.field_type == 2 else value
        await self._coordinator.async_write(self._field.sp, payload)
