"""The Renogy Gateway integration."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import RenogyConfigEntry, RenogyCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
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
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RenogyConfigEntry) -> bool:
    """Unload a Renogy Gateway config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok and hasattr(entry, "runtime_data"):
        await entry.runtime_data.async_shutdown()
    return unload_ok
