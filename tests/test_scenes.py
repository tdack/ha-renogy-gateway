"""Tests for Renogy Gateway scene support (REST + RTM + button/switch)."""

import dataclasses
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.renogy_gateway.api.rest import RenogyREST
from custom_components.renogy_gateway.api.rtm import RenogyRTM
from custom_components.renogy_gateway.button import RenogySceneButton
from custom_components.renogy_gateway.coordinator import RenogyCoordinator
from custom_components.renogy_gateway.switch import RenogyAutoSceneSwitch

from .conftest import MOCK_AUTO_SCENE, MOCK_GATEWAY_NAME, MOCK_MANUAL_SCENE


# ---------------------------------------------------------------------------
# REST: get_scenes / update_scene
# ---------------------------------------------------------------------------


async def test_get_scenes_fetches_manual_and_auto() -> None:
    """get_scenes fetches type=2 (manual) and type=3 (auto) and tags each."""
    rest = RenogyREST.__new__(RenogyREST)
    rest._get_scenes_by_type = AsyncMock(  # noqa: SLF001
        side_effect=[
            [{"id": 1, "sceneName": "Away", "conditionType": 1}],
            [{"id": 2, "sceneName": "Cooling On", "conditionType": 4, "isOpen": True}],
        ]
    )

    scenes = await rest.get_scenes("227162568538456065")

    assert {s.id: s.is_manual for s in scenes} == {"1": True, "2": False}
    auto = next(s for s in scenes if s.id == "2")
    assert auto.is_open is True
    assert auto.raw == {"id": 2, "sceneName": "Cooling On", "conditionType": 4, "isOpen": True}


async def test_update_scene_echoes_raw_body_with_flipped_open() -> None:
    """update_scene echoes the stored raw scene back with isOpen/isManual set,
    matching the dashboard's bridge.ts updateScene call (full-object write)."""
    rest = RenogyREST.__new__(RenogyREST)
    rest._post = AsyncMock(return_value={"code": "000000"})  # noqa: SLF001

    await rest.update_scene(MOCK_AUTO_SCENE, is_open=False)

    rest._post.assert_awaited_once()
    path, body = rest._post.call_args.args
    assert path == "/api/v2/device/scene/updateScene"
    assert body["id"] == MOCK_AUTO_SCENE.raw["id"]
    assert body["isOpen"] is False
    assert body["isManual"] is False  # conditionType 4 → auto


# ---------------------------------------------------------------------------
# RTM: run_scene
# ---------------------------------------------------------------------------


async def test_rtm_run_scene_sends_op6_rpc() -> None:
    """run_scene issues op-6 to '<gwDid>/scene.run' with the sceneId payload."""
    rtm = RenogyRTM.__new__(RenogyRTM)
    rtm._call = AsyncMock(return_value={"code": 0})  # noqa: SLF001

    ack = await rtm.run_scene("227162568538456065", 2400162031240761)

    assert ack == {"code": 0}
    frame = rtm._call.call_args.args[0]
    assert frame["op"] == 6
    assert frame["sp"] == "227162568538456065/scene.run"
    assert frame["data"] == {"sceneId": 2400162031240761}


# ---------------------------------------------------------------------------
# Coordinator: async_run_scene / async_set_scene_open
# ---------------------------------------------------------------------------


async def test_async_run_scene_unknown_id_raises(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Running an unknown scene id raises instead of calling the RTM."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator._rtm.run_scene = AsyncMock()

    with pytest.raises(HomeAssistantError):
        await coordinator.async_run_scene("does-not-exist")
    coordinator._rtm.run_scene.assert_not_awaited()


async def test_async_run_scene_calls_rtm(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Running a known scene calls RTM.run_scene with the gateway did + int id."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    coordinator.scenes = {MOCK_MANUAL_SCENE.id: MOCK_MANUAL_SCENE}
    coordinator._rtm.run_scene = AsyncMock(return_value={"code": 0})

    await coordinator.async_run_scene(MOCK_MANUAL_SCENE.id)

    coordinator._rtm.run_scene.assert_awaited_once_with(
        MOCK_MANUAL_SCENE.gateway_did, int(MOCK_MANUAL_SCENE.id)
    )


async def test_async_set_scene_open_updates_state_and_fires_callback(
    hass: HomeAssistant, mock_config_entry
) -> None:
    """Toggling an Auto scene updates local state and notifies listeners."""
    mock_config_entry.add_to_hass(hass)
    coordinator = RenogyCoordinator(hass, mock_config_entry)
    # Use a private copy — async_set_scene_open mutates SceneInfo.is_open in
    # place, and MOCK_AUTO_SCENE is a shared module-level fixture.
    scene = dataclasses.replace(MOCK_AUTO_SCENE)
    coordinator.scenes = {scene.id: scene}
    coordinator._rest.update_scene = AsyncMock()
    seen = []
    coordinator.register_scene_callback(lambda: seen.append(True))

    await coordinator.async_set_scene_open(scene.id, False)

    coordinator._rest.update_scene.assert_awaited_once_with(scene, is_open=False)
    assert coordinator.scenes[scene.id].is_open is False
    assert seen == [True]


# ---------------------------------------------------------------------------
# Entities: button (Manual) + switch (Auto enable)
# ---------------------------------------------------------------------------


async def test_scene_button_press_runs_scene(mock_coordinator) -> None:
    """Pressing the button calls coordinator.async_run_scene."""
    button = RenogySceneButton(mock_coordinator, MOCK_GATEWAY_NAME, MOCK_MANUAL_SCENE)
    await button.async_press()
    mock_coordinator.async_run_scene.assert_awaited_once_with(MOCK_MANUAL_SCENE.id)


async def test_auto_scene_switch_reflects_is_open(mock_coordinator) -> None:
    """The Auto scene switch's is_on tracks SceneInfo.is_open."""
    switch = RenogyAutoSceneSwitch(mock_coordinator, MOCK_GATEWAY_NAME, MOCK_AUTO_SCENE)
    assert switch.is_on is True


async def test_auto_scene_switch_turn_off_calls_coordinator(mock_coordinator) -> None:
    """Turning the switch off calls coordinator.async_set_scene_open(False)."""
    switch = RenogyAutoSceneSwitch(mock_coordinator, MOCK_GATEWAY_NAME, MOCK_AUTO_SCENE)
    await switch.async_turn_off()
    mock_coordinator.async_set_scene_open.assert_awaited_once_with(
        MOCK_AUTO_SCENE.id, False
    )


async def test_scene_entity_unavailable_when_scene_disappears(mock_coordinator) -> None:
    """A scene entity becomes unavailable if its scene id vanishes from the
    coordinator's scene list (e.g. deleted via the app)."""
    switch = RenogyAutoSceneSwitch(mock_coordinator, MOCK_GATEWAY_NAME, MOCK_AUTO_SCENE)
    mock_coordinator.scenes = {}
    assert switch.available is False
