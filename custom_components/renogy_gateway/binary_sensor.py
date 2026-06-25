"""Binary sensor platform for Renogy Gateway — read-only boolean telemetry."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import FieldSpec, RenogyDevice
from .const import is_diagnostic_field
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity

PARALLEL_UPDATES = 0


def _is_binary_sensor(field: FieldSpec) -> bool:
    """Return True if this field should be a binary sensor entity."""
    return not field.writable and field.field_type == 1  # read-only bool


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Renogy binary sensor entities from a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data
    entities = [
        RenogyBinarySensor(coordinator, device, field)
        for device in coordinator.devices.values()
        for field in device.fields
        if _is_binary_sensor(field)
    ]
    async_add_entities(entities)


class RenogyBinarySensor(RenogyBaseEntity, BinarySensorEntity):
    """A read-only boolean binary sensor from Renogy telemetry."""

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
    ) -> None:
        """Initialize the binary sensor, marking status-like fields diagnostic."""
        super().__init__(coordinator, device, field)
        if is_diagnostic_field(field.sp):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        """Return True if the sensor reports an active (true) state."""
        if self._value is None:
            return None
        return bool(self._value)
