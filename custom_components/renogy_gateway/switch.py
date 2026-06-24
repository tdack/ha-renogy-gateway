"""Switch platform for Renogy Gateway — writable boolean fields (DC outputs)."""

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api.models import FieldSpec, RenogyDevice
from .coordinator import RenogyConfigEntry, RenogyCoordinator
from .entity import RenogyBaseEntity

PARALLEL_UPDATES = 0

_MEASUREMENT_LEAVES = ("power", "current", "voltage", "ratio")


def _has_ratio_sibling(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this channel has a writable '.ratio' sibling field.

    A '.state' field that has a writable ratio sibling maps to a light, not a switch.
    """
    channel_key = field.channel_key
    if not channel_key:
        return False
    ratio_sp = field.sp.rsplit(".", 1)[0] + ".ratio"
    return any(f.sp == ratio_sp and f.writable for f in device.fields)


def _has_measurement_sibling(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this channel has a readable power/current/voltage/ratio sibling.

    That measurement is what distinguishes a real, physically-wired load
    channel from a standalone configuration boolean (e.g. an inverter mode toggle).
    """
    channel_key = field.channel_key
    if not channel_key:
        return False
    prefix = field.sp.rsplit(".", 1)[0]
    return any(
        f.sp.rsplit(".", 1)[0] == prefix
        and f.sp.rsplit(".", 1)[-1] in _MEASUREMENT_LEAVES
        and f.readable
        for f in device.fields
    )


def _is_controllable_bool(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this field is a writable boolean not handled by light.py."""
    return (
        field.writable
        and field.field_type == 1  # bool
        and not _has_ratio_sibling(field, device)
    )


def _is_load_switch(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this field is a primary control for a real load channel."""
    return _is_controllable_bool(field, device) and _has_measurement_sibling(
        field, device
    )


def _is_config_switch(field: FieldSpec, device: RenogyDevice) -> bool:
    """Return True if this field is a standalone configuration toggle."""
    return _is_controllable_bool(field, device) and not _has_measurement_sibling(
        field, device
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RenogyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Renogy switch entities from a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data
    entities = [
        RenogySwitch(
            coordinator, device, field, is_config=_is_config_switch(field, device)
        )
        for device in coordinator.devices.values()
        for field in device.fields
        if _is_load_switch(field, device) or _is_config_switch(field, device)
    ]
    async_add_entities(entities)


class RenogySwitch(RenogyBaseEntity, RestoreEntity, SwitchEntity):
    """A writable boolean switch mapped to a Renogy DC output channel."""

    def __init__(
        self,
        coordinator: RenogyCoordinator,
        device: RenogyDevice,
        field: FieldSpec,
        is_config: bool = False,
    ) -> None:
        """Initialize the switch, marking standalone toggles as configuration entities."""
        super().__init__(coordinator, device, field)
        if is_config:
            self._attr_entity_category = EntityCategory.CONFIG

    async def async_added_to_hass(self) -> None:
        """Restore last state on startup, if the coordinator has no live value yet."""
        await super().async_added_to_hass()
        if (
            self._value is None
            and (last_state := await self.async_get_last_state()) is not None
        ):
            self._value = last_state.state == "on"

    @property
    def is_on(self) -> bool | None:
        """Return True if the switch reports an on state."""
        if self._value is None:
            return None
        return bool(self._value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._coordinator.async_write(self._field.sp, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._coordinator.async_write(self._field.sp, False)
