"""Tests for the Renogy Gateway number platform."""

from custom_components.renogy_gateway.number import _is_number

from .conftest import (
    FIELD_CHARGE_VOLTAGE,
    FIELD_LIGHT_RATIO,
    MOCK_BOX_DEVICE,
    MOCK_CHARGER_DEVICE,
)


def test_light_ratio_field_excluded_from_number() -> None:
    """A dimmable light's ratio field is not duplicated as a number entity."""
    assert _is_number(FIELD_LIGHT_RATIO, MOCK_BOX_DEVICE) is False


def test_writable_bounded_field_is_number() -> None:
    """A plain writable bounded field (no light sibling) is still a number."""
    assert _is_number(FIELD_CHARGE_VOLTAGE, MOCK_CHARGER_DEVICE) is True
