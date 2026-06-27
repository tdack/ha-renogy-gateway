"""Tests for the Renogy Gateway integration setup (__init__.py)."""

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.renogy_gateway import async_setup_entry
from custom_components.renogy_gateway.api.models import RenogyDevice
from custom_components.renogy_gateway.const import DOMAIN


async def test_device_with_no_fields_still_gets_registered(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Real-world regression: "Vision" (namespaces thing + version_ctrl, both
    always namespace-skipped) has zero entities. HA only creates a device
    record implicitly via an entity's device_info, so without an explicit
    device-registry registration, a zero-field device would never appear at
    all — even though it's a real child of the gateway."""
    mock_config_entry.add_to_hass(hass)

    vision = RenogyDevice(
        did_str="4646428229905819205",
        pid="002C0000",
        sku="",
        name="Vision",
        online=True,
        fields=[],
        protocol="wifi",
        sw_version="V11.5.3",
    )

    mock_coordinator = AsyncMock()
    mock_coordinator.devices = {vision.did_str: vision}
    mock_coordinator.scenes = {}

    with (
        patch(
            "custom_components.renogy_gateway.RenogyCoordinator",
            return_value=mock_coordinator,
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", AsyncMock()
        ),
    ):
        result = await async_setup_entry(hass, mock_config_entry)

    assert result is True
    device_registry = dr.async_get(hass)
    entry = device_registry.async_get_device(identifiers={(DOMAIN, vision.did_str)})
    assert entry is not None
    assert entry.name == "Vision"
    assert entry.sw_version == "V11.5.3"
