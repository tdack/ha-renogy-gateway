"""Authentication for the Renogy DC Home private API."""

import base64
from collections.abc import Callable, Coroutine
import json
import logging
import time
from typing import Any
import uuid

import aiohttp

from .models import TokenSet

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://gateway.renogy.com"
REFRESH_SKEW = 60  # seconds before expiry to proactively refresh

CLIENT_HEADERS = {
    "app-version": "1.8.82",
    "device-version": "26.5",
    "device-mode": "iPad8,6",
    "device-manufacturer": "Apple",
    "request-channel": "ios",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "Accept-Language": "en-US",
    "User-Agent": (
        "Renogy/1.8.82 (com.renogy.DCHome; build:2; iOS 26.5.0) Alamofire/5.11.2"
    ),
}

# Cold-boot app-register constants (the iOS app's product + node type)
_APP_REGISTER_PID = "003F0000"
_APP_NODE_TYPE = 4


class RenogyAuthError(Exception):
    """Raised when authentication fails (bad credentials)."""


class RenogyConnectionError(Exception):
    """Raised when the Renogy API cannot be reached."""


def _jwt_claims(token: str) -> dict:
    """Decode JWT claims without verifying the signature."""
    segment = token.split(".")[1]
    segment += "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment))


class RenogyAuth:
    """Handles Renogy account authentication and token lifecycle.

    Tokens rotate on every refresh — callers must persist updated tokens
    immediately via the on_token_refresh callback.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        on_token_refresh: Callable[[TokenSet], Coroutine[Any, Any, None]],
        device_uuid: str | None = None,
    ) -> None:
        """Initialize with an aiohttp session and a persistence callback."""
        self._session = session
        self._on_token_refresh = on_token_refresh
        self._tokens: TokenSet | None = None
        # Persistent local UUID — server requires identity-uuid on every call
        # including first login. Seeded from stored tokens when available.
        self._device_uuid = device_uuid or str(uuid.uuid4())

    def set_tokens(self, tokens: TokenSet) -> None:
        """Seed the auth layer with previously persisted tokens."""
        self._tokens = tokens
        self._device_uuid = tokens.device_uuid or self._device_uuid

    @property
    def tokens(self) -> TokenSet:
        """Return current tokens, raising if not yet set."""
        if self._tokens is None:
            raise RuntimeError("RenogyAuth: tokens not initialised")
        return self._tokens

    def _headers(self) -> dict[str, str]:
        h = dict(CLIENT_HEADERS)
        h["identity-uuid"] = self._device_uuid
        if self._tokens:
            h["x-token"] = self._tokens.access_token
        return h

    def _access_token_fresh(self) -> bool:
        if not self._tokens:
            return False
        try:
            claims = _jwt_claims(self._tokens.access_token)
            return claims["exp"] - REFRESH_SKEW > time.time()
        except KeyError, IndexError, ValueError:
            return False

    async def login(self, email: str, password: str) -> TokenSet:
        """Login with email + password and return a TokenSet.

        SECURITY: password is sent cleartext — never log request bodies.
        """
        try:
            async with self._session.post(
                f"{BASE_URL}/api/v1/account/app/do_login",
                headers=self._headers(),
                json={"loginType": 0, "identifier": email, "credential": password},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 401:
                    raise RenogyAuthError("Invalid email or password")
                resp.raise_for_status()
                body = await resp.json()
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"Cannot connect to Renogy: {err}") from err

        data = body["data"]
        access_token = data["accessToken"]
        refresh_token = data["refreshToken"]
        claims = _jwt_claims(access_token)
        device_uuid = claims.get("device_uuid", "")

        # Cold-boot: mint the first RTM token via app-register
        rtm_token, rtm_did = await self._app_register(access_token, device_uuid, email)

        tokens = TokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            rtm_token=rtm_token,
            rtm_did=rtm_did,
            device_uuid=device_uuid,
        )
        self._tokens = tokens
        await self._on_token_refresh(tokens)
        return tokens

    async def _app_register(
        self, access_token: str, device_uuid: str, email: str
    ) -> tuple[str, str]:
        """Mint the first RTM token for a new session (cold-boot path)."""
        headers = dict(CLIENT_HEADERS)
        headers["x-token"] = access_token
        headers["identity-uuid"] = device_uuid
        sn = f"{device_uuid}#{email}"
        try:
            async with self._session.post(
                f"{BASE_URL}/api/v2/device/app-register",
                headers=headers,
                json={"pid": _APP_REGISTER_PID, "sn": sn, "nodeType": _APP_NODE_TYPE},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"Cannot register RTM session: {err}") from err
        rtm_data = body["data"]
        return rtm_data["token"], str(rtm_data["didStr"])

    async def ensure_fresh(self) -> None:
        """Refresh the access token if it is expired or about to expire."""
        if not self._access_token_fresh():
            await self._refresh_access()

    async def _refresh_access(self) -> None:
        """Rotate the access + refresh token pair. Persists immediately."""
        tokens = self.tokens
        try:
            async with self._session.post(
                f"{BASE_URL}/api/v1/account/app/do_refresh",
                headers=self._headers(),
                json={"refreshToken": tokens.refresh_token},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status in (401, 999):
                    raise RenogyAuthError("Refresh token rejected — re-login required")
                resp.raise_for_status()
                body = await resp.json()
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"Token refresh failed: {err}") from err

        data = body["data"]
        # Old refresh token is now dead — persist the rotated pair immediately
        updated = TokenSet(
            access_token=data["accessToken"],
            refresh_token=data["refreshToken"],
            rtm_token=tokens.rtm_token,
            rtm_did=tokens.rtm_did,
            device_uuid=tokens.device_uuid,
        )
        self._tokens = updated
        await self._on_token_refresh(updated)

    async def refresh_rtm_token(self) -> tuple[str, str]:
        """Rotate the RTM device token. Returns (rtm_token, rtm_did).

        Accepts an expired prior token — rotate indefinitely from any valid seed.
        """
        await self.ensure_fresh()
        tokens = self.tokens
        try:
            async with self._session.post(
                f"{BASE_URL}/api/v2/device/refresh-token",
                headers=self._headers(),
                json={"token": tokens.rtm_token},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                resp.raise_for_status()
                # Extract did_str from raw text before JSON parse to avoid float64 precision loss
                raw = await resp.text()
                body = json.loads(raw)
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"RTM token refresh failed: {err}") from err

        rtm_data = body["data"]
        rtm_token = rtm_data["token"]
        # did is int64 — JSON float64 loses precision; use the raw string if provided
        did_str = str(rtm_data.get("didStr") or rtm_data["did"])

        updated = TokenSet(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            rtm_token=rtm_token,
            rtm_did=did_str,
            device_uuid=tokens.device_uuid,
        )
        self._tokens = updated
        await self._on_token_refresh(updated)
        return rtm_token, did_str
