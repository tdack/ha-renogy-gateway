"""Diagnostics for the Renogy Gateway integration."""

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import RenogyConfigEntry, RenogyCoordinator

_REDACT = {
    "email",
    "password",
    "access_token",
    "refresh_token",
    "rtm_token",
    "rtm_did",
    "device_uuid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RenogyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: RenogyCoordinator = entry.runtime_data

    redacted_data = {
        k: "**REDACTED**" if k in _REDACT else v for k, v in entry.data.items()
    }

    devices_info = [
        {
            "did_str": device.did_str,
            "pid": device.pid,
            "sku": device.sku,
            "name": device.name,
            "online": device.online,
            "field_count": len(device.fields),
            "writable_fields": sum(1 for f in device.fields if f.writable),
            "subscribable_fields": sum(1 for f in device.fields if f.subscribable),
        }
        for device in coordinator.devices.values()
    ]

    return {
        "entry_data": redacted_data,
        "devices": devices_info,
        "total_devices": len(coordinator.devices),
        "total_fields": sum(len(d.fields) for d in coordinator.devices.values()),
    }
