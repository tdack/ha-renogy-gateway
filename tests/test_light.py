"""Tests for the Renogy Gateway light platform."""

import math
from unittest.mock import MagicMock

from homeassistant.components.light import ATTR_BRIGHTNESS
from custom_components.renogy_gateway.light import RenogyLight
from homeassistant.core import HomeAssistant

from .conftest import FIELD_LIGHT_RATIO, FIELD_LIGHT_STATE, MOCK_BOX_DEVICE


async def test_light_turn_on_no_brightness(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Turn on without brightness just writes state=True."""
    light = RenogyLight(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_LIGHT_STATE, FIELD_LIGHT_RATIO
    )
    light.hass = hass

    await light.async_turn_on()
    mock_coordinator.async_write.assert_awaited_once_with(FIELD_LIGHT_STATE.sp, True)


async def test_light_turn_on_with_brightness(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Turn on with brightness=128 writes ratio=50 then state=True."""
    light = RenogyLight(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_LIGHT_STATE, FIELD_LIGHT_RATIO
    )
    light.hass = hass

    await light.async_turn_on(**{ATTR_BRIGHTNESS: 128})

    calls = mock_coordinator.async_write.await_args_list
    assert len(calls) == 2
    # First call: ratio ≈ 50%
    ratio_call = calls[0]
    assert ratio_call.args[0] == FIELD_LIGHT_RATIO.sp
    assert ratio_call.args[1] == round(128 / 255 * 100)
    # Second call: state=True
    assert calls[1].args == (FIELD_LIGHT_STATE.sp, True)


async def test_light_turn_off(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Turn off writes state=False."""
    light = RenogyLight(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_LIGHT_STATE, FIELD_LIGHT_RATIO
    )
    light.hass = hass

    await light.async_turn_off()
    mock_coordinator.async_write.assert_awaited_once_with(FIELD_LIGHT_STATE.sp, False)


async def test_light_brightness_from_ratio_push(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Brightness property reflects incoming ratio telemetry."""
    light = RenogyLight(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_LIGHT_STATE, FIELD_LIGHT_RATIO
    )
    light.hass = hass
    light.async_write_ha_state = MagicMock()

    assert light.brightness is None

    light._handle_ratio(75)
    assert light.brightness == math.ceil(75 / 100 * 255)
    light.async_write_ha_state.assert_called_once()


async def test_light_name_from_user_label(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Light name uses user-assigned label."""
    light = RenogyLight(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_LIGHT_STATE, FIELD_LIGHT_RATIO
    )
    assert light.name == "Bedroom Light"


async def test_light_seeds_state_and_brightness_from_coordinator_cache(
    hass: HomeAssistant,
    mock_coordinator,
) -> None:
    """Cached live state + ratio values seed is_on/brightness immediately."""
    mock_coordinator.get_value.side_effect = lambda sp: {
        FIELD_LIGHT_STATE.sp: True,
        FIELD_LIGHT_RATIO.sp: 50,
    }.get(sp)
    light = RenogyLight(
        mock_coordinator, MOCK_BOX_DEVICE, FIELD_LIGHT_STATE, FIELD_LIGHT_RATIO
    )
    light.hass = hass
    light.entity_id = "light.test_bedroom"
    light.async_write_ha_state = MagicMock()

    await light.async_added_to_hass()
    assert light.is_on is True
    assert light.brightness == math.ceil(50 / 100 * 255)
