"""Tests for the Renogy Gateway binary sensor platform."""

from homeassistant.const import EntityCategory

from custom_components.renogy_gateway.binary_sensor import RenogyBinarySensor

from .conftest import FIELD_ONLINE, MOCK_BOX_DEVICE


def test_online_field_is_diagnostic(mock_coordinator) -> None:
    """An '.online' field is tucked into the Diagnostic section, matching
    apps/hass-bridge/src/filter.ts diagnosticPatterns in the sibling repo."""
    sensor = RenogyBinarySensor(mock_coordinator, MOCK_BOX_DEVICE, FIELD_ONLINE)
    assert sensor.entity_category == EntityCategory.DIAGNOSTIC
