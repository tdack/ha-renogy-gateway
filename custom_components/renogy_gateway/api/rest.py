"""REST API calls for Renogy DC Home (device lists, scenes)."""

import logging

import aiohttp

from .auth import RenogyAuth, RenogyConnectionError
from .models import GatewayInfo

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://gateway.renogy.com"


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
