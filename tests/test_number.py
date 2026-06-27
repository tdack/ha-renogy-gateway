"""Tests for the Renogy Gateway number platform."""

from unittest.mock import AsyncMock

from custom_components.renogy_gateway.number import RenogyNumber, _is_number

from .conftest import (
    FIELD_CHARGE_VOLTAGE,
    FIELD_DESIRED_VOLTAGE_MV,
    FIELD_LIGHT_RATIO,
    FIELD_MAX_CURRENT_ZH_UNIT,
    FIELD_UNBOUNDED_NUMBER,
    MOCK_BOX_DEVICE,
    MOCK_CHARGER_DEVICE,
    MOCK_INVERTER_DEVICE,
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


async def test_millivolt_number_normalised_to_volts(mock_coordinator) -> None:
    """A writable field reported in mV displays/edits in V, with bounds
    scaled too, and a 2dp-capped default precision when the schema doesn't
    specify one (real-world regression: "14.349999" instead of "14.35")."""
    number = RenogyNumber(mock_coordinator, MOCK_INVERTER_DEVICE, FIELD_DESIRED_VOLTAGE_MV)

    assert number.native_unit_of_measurement == "V"
    assert number.native_min_value == 12.0
    assert number.native_max_value == 15.0
    assert number.native_step == 0.01  # drives display/edit rounding to 2dp

    number._value = 14349.999  # raw wire value, in mV
    assert round(number.native_value, 2) == 14.35


async def test_millivolt_number_write_converts_back_to_raw_units(
    mock_coordinator,
) -> None:
    """Writing a displayed value (V) converts it back to the wire unit (mV)
    before sending — the inverse of the read-side scaling."""
    mock_coordinator.async_write = AsyncMock()
    number = RenogyNumber(mock_coordinator, MOCK_INVERTER_DEVICE, FIELD_DESIRED_VOLTAGE_MV)

    await number.async_set_native_value(14.35)

    mock_coordinator.async_write.assert_awaited_once()
    sp, payload = mock_coordinator.async_write.call_args.args
    assert sp == FIELD_DESIRED_VOLTAGE_MV.sp
    assert round(payload, 2) == 14350.0


async def test_chinese_ampere_unit_translated(mock_coordinator) -> None:
    """charger.max_current reports unit "安培" (Chinese for Ampere) on some
    rigs — must translate to "A" like other current entities, not show the
    raw Chinese characters."""
    number = RenogyNumber(mock_coordinator, MOCK_INVERTER_DEVICE, FIELD_MAX_CURRENT_ZH_UNIT)
    assert number.native_unit_of_measurement == "A"
