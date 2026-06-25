"""Tests for the Renogy Gateway number platform."""

from custom_components.renogy_gateway.number import RenogyNumber, _is_number

from .conftest import (
    FIELD_CHARGE_VOLTAGE,
    FIELD_LIGHT_RATIO,
    FIELD_UNBOUNDED_NUMBER,
    MOCK_BOX_DEVICE,
    MOCK_CHARGER_DEVICE,
)


def test_light_ratio_field_excluded_from_number() -> None:
    """A dimmable light's ratio field is not duplicated as a number entity."""
    assert _is_number(FIELD_LIGHT_RATIO, MOCK_BOX_DEVICE) is False


def test_writable_bounded_field_is_number() -> None:
    """A plain writable bounded field (no light sibling) is still a number."""
    assert _is_number(FIELD_CHARGE_VOLTAGE, MOCK_CHARGER_DEVICE) is True


def test_writable_unbounded_field_is_still_number() -> None:
    """A writable field with no schema min/max is not dropped — it's a number
    with a generous fallback range, matching the dashboard's optional-bounds
    treatment (DeviceModal.svelte only checks min/max when present)."""
    assert _is_number(FIELD_UNBOUNDED_NUMBER, MOCK_CHARGER_DEVICE) is True


async def test_unbounded_number_gets_fallback_range(mock_coordinator) -> None:
    """An unbounded field gets a generous, not 0-100, fallback range."""
    number = RenogyNumber(mock_coordinator, MOCK_CHARGER_DEVICE, FIELD_UNBOUNDED_NUMBER)
    assert number.native_min_value == -1_000_000.0
    assert number.native_max_value == 1_000_000.0
