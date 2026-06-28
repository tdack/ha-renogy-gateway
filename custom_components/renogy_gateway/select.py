"""Select platform for Renogy Gateway — writable enum configuration fields."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.labels import ZH_OPTION
from .api.models import FieldSpec, RenogyDevice
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity

PARALLEL_UPDATES = 0


def _is_select(field: FieldSpec) -> bool:
    """Return True if this field should be a select entity."""
    return field.writable and bool(field.options)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Renogy select entities from a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data
    entities = [
        RenogySelect(coordinator, device, field)
        for device in coordinator.devices.values()
        for field in device.fields
        if _is_select(field)
    ]
    async_add_entities(entities)


class RenogySelect(RenogyBaseEntity, SelectEntity):
    """A writable enum configuration field."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
    ) -> None:
        """Initialize the select entity and build option label maps."""
        super().__init__(coordinator, device, field)
        assert field.options is not None
        # options is [{key, value}]; expose 'value' (display label) to HA,
        # translating any Chinese schema-supplied labels to English.
        self._key_to_label: dict[str, str] = {
            str(opt["key"]): ZH_OPTION.get(str(opt["value"]), str(opt["value"]))
            for opt in field.options
        }
        self._label_to_key: dict[str, str] = {
            v: k for k, v in self._key_to_label.items()
        }
        self._attr_options = list(self._key_to_label.values())

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option label."""
        if self._value is None:
            return None
        return self._key_to_label.get(str(self._value))

    async def async_select_option(self, option: str) -> None:
        """Write the selected option's key to the field."""
        key = self._label_to_key.get(option)
        if key is None:
            return
        # Write the raw key (int or str depending on original type)
        try:
            payload: int | str = int(key)
        except ValueError:
            payload = key
        await self._coordinator.async_write(self._field.sp, payload)
