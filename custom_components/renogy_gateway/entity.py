"""Base entity class for Renogy Gateway entities."""

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .api.models import FieldSpec, RenogyDevice, SceneInfo
from .const import DOMAIN
from .coordinator import RenogyCoordinator


class RenogyBaseEntity(Entity):
    """Base class for all Renogy Gateway entities.

    Entities receive telemetry via coordinator callbacks rather than polling.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
    ) -> None:
        """Initialize entity with coordinator, device, and field references."""
        self._coordinator = coordinator
        self._device = device
        self._field = field
        self._value: Any = None
        self._available = True

        self._attr_unique_id = f"renogy_{field.sp}"
        self._attr_name = field.display_name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.did_str)},
            name=device.name,
            manufacturer="Renogy",
            model=device.sku,
        )

    @property
    def available(self) -> bool:
        """Return True if the RTM connection is live."""
        return self._available

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to HA."""
        cached = self._coordinator.get_value(self._field.sp)
        if cached is not None:
            self._value = cached
        self._coordinator.register_telemetry_callback(
            self._field.sp, self._handle_telemetry
        )
        self._coordinator.register_availability_callback(self._handle_availability)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        self._coordinator.unregister_telemetry_callback(
            self._field.sp, self._handle_telemetry
        )
        self._coordinator.unregister_availability_callback(self._handle_availability)

    @callback
    def _handle_telemetry(self, value: Any) -> None:
        """Process an incoming telemetry push for this entity's sp."""
        self._value = value
        self._available = True
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool) -> None:
        """Handle RTM connect/disconnect events."""
        self._available = available
        self.async_write_ha_state()


class RenogySceneEntity(Entity):
    """Base class for scene entities (button/switch), keyed by scene id
    rather than a field sp — scenes come from REST CRUD, not the schema-
    driven field pipeline (PROTOCOL.md §8)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        gateway_name: str,
        scene: SceneInfo,
    ) -> None:
        """Initialize the scene entity, attached to the gateway device."""
        self._coordinator = coordinator
        self._scene_id = scene.id
        self._available = True

        self._attr_unique_id = f"renogy_scene_{scene.id}"
        self._attr_name = scene.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, scene.gateway_did)},
            name=gateway_name,
            manufacturer="Renogy",
            model="ONE Core",
        )

    @property
    def _scene(self) -> SceneInfo | None:
        """Return the current SceneInfo, or None if it's gone missing."""
        return self._coordinator.scenes.get(self._scene_id)

    @property
    def available(self) -> bool:
        """Return True if the RTM connection is live and the scene still exists."""
        return self._available and self._scene is not None

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added to HA."""
        self._coordinator.register_scene_callback(self._handle_scene_update)
        self._coordinator.register_availability_callback(self._handle_availability)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callbacks when entity is removed."""
        self._coordinator.unregister_scene_callback(self._handle_scene_update)
        self._coordinator.unregister_availability_callback(self._handle_availability)

    @callback
    def _handle_scene_update(self) -> None:
        """Process a scene-state change (e.g. Auto enable toggled)."""
        self.async_write_ha_state()

    @callback
    def _handle_availability(self, available: bool) -> None:
        """Handle RTM connect/disconnect events."""
        self._available = available
        self.async_write_ha_state()
