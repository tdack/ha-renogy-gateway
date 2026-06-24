"""Base entity class for Renogy Gateway entities."""

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .api.models import FieldSpec, RenogyDevice
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
