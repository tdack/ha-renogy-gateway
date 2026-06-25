"""Button platform for Renogy Gateway — run a Manual scene (PROTOCOL.md §8.3)."""

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_GATEWAY_NAME
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogySceneEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a Run button for each Manual scene."""
    coordinator: RenogyCoordinator = entry.runtime_data
    gateway_name = entry.data[CONF_GATEWAY_NAME]
    entities = [
        RenogySceneButton(coordinator, gateway_name, scene)
        for scene in coordinator.scenes.values()
        if scene.is_manual
    ]
    async_add_entities(entities)


class RenogySceneButton(RenogySceneEntity, ButtonEntity):
    """Runs a Manual scene — executes a batch of writes to physical circuits."""

    async def async_press(self) -> None:
        """Run the scene."""
        await self._coordinator.async_run_scene(self._scene_id)
