"""Tests for the Renogy Gateway select platform."""

from unittest.mock import MagicMock

from custom_components.renogy_gateway.api.models import FieldSpec
from custom_components.renogy_gateway.select import RenogySelect, _is_select
from homeassistant.core import HomeAssistant

from .conftest import FIELD_SOC_RULE, MOCK_BOX_DEVICE


def test_is_select_requires_writable_and_options() -> None:
    """A select entity needs both the write bit and schema options."""
    assert _is_select(FIELD_SOC_RULE) is True

    readonly = FieldSpec(
        sp="123/x.y", name="y", field_type=2, ops=6, options=[{"key": 0, "value": "a"}]
    )
    assert _is_select(readonly) is False

    no_options = FieldSpec(sp="123/x.z", name="z", field_type=2, ops=7)
    assert _is_select(no_options) is False


async def test_select_current_option_maps_key_to_label(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """current_option resolves the raw telemetry key to its display label."""
    select = RenogySelect(mock_coordinator, MOCK_BOX_DEVICE, FIELD_SOC_RULE)
    select.hass = hass
    select.async_write_ha_state = MagicMock()

    assert select.current_option is None
    select._handle_telemetry(1)
    assert select.current_option == "Medium (50%)"


async def test_select_writes_back_the_raw_key(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Selecting an option writes its raw schema key, not the display label."""
    select = RenogySelect(mock_coordinator, MOCK_BOX_DEVICE, FIELD_SOC_RULE)
    select.hass = hass

    await select.async_select_option("Medium (50%)")

    mock_coordinator.async_write.assert_awaited_once_with(FIELD_SOC_RULE.sp, 1)


async def test_select_translates_chinese_option_labels(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Schema-supplied Chinese option labels must render in English."""
    field = FieldSpec(
        sp="123/gwmConfig.mode",
        name="mode",
        field_type=2,
        ops=7,
        options=[{"key": 0, "value": "不同步"}, {"key": 1, "value": "自动同步"}],
    )
    select = RenogySelect(mock_coordinator, MOCK_BOX_DEVICE, field)
    select.hass = hass

    assert select._attr_options == ["Off (manual)", "Auto"]

    await select.async_select_option("Auto")
    mock_coordinator.async_write.assert_awaited_once_with(field.sp, 1)
