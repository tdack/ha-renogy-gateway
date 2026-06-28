"""The Renogy Gateway integration."""

from homeassistant.const import CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import RenogyConfigEntry, RenogyCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: RenogyConfigEntry) -> bool:
    """Set up Renogy Gateway from a config entry."""
    coordinator = RenogyCoordinator(hass, entry)
    await coordinator.async_setup()
    entry.runtime_data = coordinator

    # Register every discovered device explicitly. A device whose only
    # namespaces are protocol/system internals (e.g. "Vision" — thing +
    # version_ctrl, both always skipped) has zero entities, and HA only
    # creates a device record implicitly via an entity's device_info — so
    # without this, such a device would never appear at all.
    device_registry = dr.async_get(hass)
    for device in coordinator.devices.values():
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, device.did_str)},
            name=device.name,
            manufacturer="Renogy",
            model=device.sku,
            sw_version=device.sw_version,
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RenogyConfigEntry) -> bool:
    """Unload a Renogy Gateway config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and hasattr(entry, "runtime_data"):
        await entry.runtime_data.async_shutdown()
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: RenogyConfigEntry) -> bool:
    """Migrate an old config entry to the current version.

    Version 2 drops the persisted account password — it was written to
    `.storage` but never read back (login only ever runs with freshly
    user-entered credentials), so it was pure disk-exposure risk.
    """
    if entry.version == 1:
        new_data = dict(entry.data)
        new_data.pop(CONF_PASSWORD, None)
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
    return True
