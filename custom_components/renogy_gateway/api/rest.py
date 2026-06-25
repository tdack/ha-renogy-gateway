"""REST API calls for Renogy DC Home (device lists, scenes)."""

import logging

import aiohttp

from .auth import RenogyAuth, RenogyConnectionError
from .models import GatewayInfo, SceneInfo

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://gateway.renogy.com"

# getUserScenes `type` filter (PROTOCOL.md §8.1): 1 = favourites, 2 = manual, 3 = auto.
_SCENE_TYPE_MANUAL = 2
_SCENE_TYPE_AUTO = 3


class RenogyREST:
    """Thin REST wrapper that handles auth automatically."""

    def __init__(self, session: aiohttp.ClientSession, auth: RenogyAuth) -> None:
        """Initialize with an aiohttp session and auth handler."""
        self._session = session
        self._auth = auth

    async def _get(self, path: str) -> dict:
        await self._auth.ensure_fresh()
        headers = self._auth._headers()  # noqa: SLF001
        try:
            async with self._session.get(
                f"{BASE_URL}{path}",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 999):
                    await self._auth.ensure_fresh()
                    headers = self._auth._headers()  # noqa: SLF001
                    async with self._session.get(
                        f"{BASE_URL}{path}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as retry:
                        retry.raise_for_status()
                        return await retry.json()
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"REST request failed: {err}") from err

    async def _post(self, path: str, body: dict) -> dict:
        await self._auth.ensure_fresh()
        headers = self._auth._headers()  # noqa: SLF001
        try:
            async with self._session.post(
                f"{BASE_URL}{path}",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 999):
                    await self._auth.ensure_fresh()
                    headers = self._auth._headers()  # noqa: SLF001
                    async with self._session.post(
                        f"{BASE_URL}{path}",
                        headers=headers,
                        json=body,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as retry:
                        retry.raise_for_status()
                        return await retry.json()
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"REST request failed: {err}") from err

    async def get_gateways(self) -> list[GatewayInfo]:
        """Return all gateways (Renogy ONE Core devices) for this account."""
        body = await self._get("/api/v2/device/getUserGateways")
        gateway_list = (body.get("data") or {}).get("gatewayList") or []
        return [
            GatewayInfo(
                did_str=str(raw.get("did_str") or raw.get("did", "")),
                name=raw.get("deviceName") or raw.get("name") or "Renogy Gateway",
                online=bool(raw.get("onlineStatus") or raw.get("online", True)),
            )
            for raw in gateway_list
        ]

    async def _get_scenes_by_type(self, gateway_did: str, scene_type: int) -> list[dict]:
        body = await self._get(
            f"/api/v2/device/scene/getUserScenes?gatewayDeviceId={gateway_did}&type={scene_type}"
        )
        return (body.get("data") or {}).get("scenes") or []

    async def get_scenes(self, gateway_did: str) -> list[SceneInfo]:
        """Return Manual + Auto scenes for a gateway (PROTOCOL.md §8.1).

        Mirrors the dashboard, which fetches type=2 (Manual) and type=3
        (Auto) and surfaces both.
        """
        manual_raw = await self._get_scenes_by_type(gateway_did, _SCENE_TYPE_MANUAL)
        auto_raw = await self._get_scenes_by_type(gateway_did, _SCENE_TYPE_AUTO)

        scenes: list[SceneInfo] = []
        for raw in manual_raw:
            scenes.append(
                SceneInfo(
                    id=str(raw["id"]),
                    name=raw.get("sceneName") or "Scene",
                    gateway_did=gateway_did,
                    is_manual=True,
                    is_open=True,
                    raw=raw,
                )
            )
        for raw in auto_raw:
            scenes.append(
                SceneInfo(
                    id=str(raw["id"]),
                    name=raw.get("sceneName") or "Scene",
                    gateway_did=gateway_did,
                    is_manual=False,
                    is_open=bool(raw.get("isOpen")),
                    raw=raw,
                )
            )
        return scenes

    async def update_scene(self, scene: SceneInfo, *, is_open: bool) -> None:
        """Toggle an Auto scene's armed state (PROTOCOL.md §8.1, §8.2).

        The API expects the full scene object echoed back, not a partial
        patch — `isManual` mirrors `conditionType` (1 = manual, 4 = auto) on
        the write side, per the dashboard's bridge.ts updateScene call.
        """
        body: dict = {
            **scene.raw,
            "isOpen": is_open,
            "isManual": scene.raw.get("conditionType") != 4,
        }
        await self._post("/api/v2/device/scene/updateScene", body)
