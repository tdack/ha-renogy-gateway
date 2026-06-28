"""Tests for the Renogy Gateway diagnostics."""

from homeassistant.core import HomeAssistant

from custom_components.renogy_gateway.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import MOCK_EMAIL, MOCK_PASSWORD


async def test_diagnostics_redacts_email_and_password(
    hass: HomeAssistant,
    mock_config_entry,
    mock_coordinator,
) -> None:
    """Email and password must never appear in plain text in diagnostics output."""
    mock_config_entry.add_to_hass(hass)
    mock_config_entry.runtime_data = mock_coordinator

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry_data"]["email"] == "**REDACTED**"
    assert diagnostics["entry_data"]["password"] == "**REDACTED**"
    assert MOCK_EMAIL not in str(diagnostics)
    assert MOCK_PASSWORD not in str(diagnostics)
