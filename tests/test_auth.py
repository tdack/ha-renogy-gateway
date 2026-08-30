"""Tests for the Renogy auth layer — token rotation and envelope handling.

Refresh tokens ROTATE and the server kills the old one on first use, so a race
here does not merely fail a request: it can persist a dead token and leave the
integration permanently unable to authenticate.
"""

import asyncio
import base64
import json
import time
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.renogy_gateway.api.auth import RenogyAuth, RenogyAuthError
from custom_components.renogy_gateway.api.models import TokenSet


def _jwt(**claims: Any) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{payload}.s"


def _fresh() -> str:
    return _jwt(exp=time.time() + 900, email="user@example.com")


def _stale() -> str:
    return _jwt(exp=time.time() - 10, email="user@example.com")


class _Resp:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(self, body: dict, status: int = 200) -> None:
        self._body = body
        self.status = status

    async def __aenter__(self) -> "_Resp":
        # A real suspension point. Without one, awaiting these coroutines never
        # yields to the event loop, so gathered callers run to completion one at
        # a time and the interleaving the race depends on cannot occur — the
        # test would pass with or without the lock.
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    async def json(self) -> dict:
        return self._body

    async def text(self) -> str:
        return json.dumps(self._body)


class _Session:
    """Records posts and replays scripted responses."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.responder = lambda url, body: _Resp({})
        self.delay = 0.0

    def post(self, url: str, **kw: Any) -> _Resp:
        self.posts.append((url, kw.get("json") or {}))
        return self.responder(url, kw.get("json") or {})

    def get(self, url: str, **kw: Any) -> _Resp:
        return self.responder(url, {})

    def post_count(self, needle: str) -> int:
        return sum(1 for url, _ in self.posts if needle in url)


def _auth(session: _Session, tokens: TokenSet | None = None) -> RenogyAuth:
    auth = RenogyAuth(session, AsyncMock())
    if tokens:
        auth.set_tokens(tokens)
    return auth


def _tokens(access: str, refresh: str = "R1") -> TokenSet:
    return TokenSet(
        access_token=access,
        refresh_token=refresh,
        rtm_token="rtm1",
        rtm_did="257470607149498369",
        device_uuid="UUID",
    )


# ---------------------------------------------------------------------------
# Concurrent rotation
# ---------------------------------------------------------------------------


async def test_concurrent_ensure_fresh_rotates_once() -> None:
    """The rotating refresh token must be spent exactly once."""
    session = _Session()
    issued = 0
    presented: list[str] = []

    def responder(url: str, body: dict) -> _Resp:
        nonlocal issued
        presented.append(body.get("refreshToken", ""))
        issued += 1
        return _Resp({"data": {"accessToken": _fresh(), "refreshToken": f"R{issued + 1}"}})

    session.responder = responder
    auth = _auth(session, _tokens(_stale()))

    await asyncio.gather(*(auth.ensure_fresh() for _ in range(8)))

    assert session.post_count("do_refresh") == 1
    assert presented == ["R1"], "R1 must never be presented twice"
    assert auth.tokens.refresh_token == "R2"


async def test_queued_caller_does_not_spend_the_new_token() -> None:
    """A coroutine that waited on the lock must re-check, not rotate again."""
    session = _Session()
    session.responder = lambda url, body: _Resp(
        {"data": {"accessToken": _fresh(), "refreshToken": "R2"}}
    )
    auth = _auth(session, _tokens(_stale()))

    await asyncio.gather(auth.ensure_fresh(), auth.ensure_fresh(), auth.ensure_fresh())
    assert session.post_count("do_refresh") == 1


async def test_later_refresh_still_rotates() -> None:
    """The guard must not latch — a subsequent stale token still refreshes."""
    session = _Session()
    n = 1

    def responder(url: str, body: dict) -> _Resp:
        nonlocal n
        n += 1
        return _Resp({"data": {"accessToken": _stale(), "refreshToken": f"R{n}"}})

    session.responder = responder
    auth = _auth(session, _tokens(_stale()))

    await auth.ensure_fresh()
    assert auth.tokens.refresh_token == "R2"
    await auth.ensure_fresh()
    assert auth.tokens.refresh_token == "R3"


# ---------------------------------------------------------------------------
# force_refresh — the 401/999 retry path
# ---------------------------------------------------------------------------


async def test_force_refresh_rotates_a_locally_fresh_token() -> None:
    """The whole point: the server rejected a token whose `exp` still looks fine.

    ensure_fresh() declines to act here, which is why the 401/999 retry used to
    re-send the very token that had just been rejected.
    """
    session = _Session()
    session.responder = lambda url, body: _Resp(
        {"data": {"accessToken": _fresh(), "refreshToken": "R2"}}
    )
    auth = _auth(session, _tokens(_fresh()))

    await auth.ensure_fresh()
    assert session.post_count("do_refresh") == 0, "locally fresh — nothing to do"

    await auth.force_refresh()
    assert session.post_count("do_refresh") == 1
    assert auth.tokens.refresh_token == "R2"


async def test_force_refresh_is_serialised_with_ensure_fresh() -> None:
    session = _Session()
    n = 1

    def responder(url: str, body: dict) -> _Resp:
        nonlocal n
        n += 1
        return _Resp({"data": {"accessToken": _fresh(), "refreshToken": f"R{n}"}})

    session.responder = responder
    auth = _auth(session, _tokens(_stale()))

    await asyncio.gather(auth.ensure_fresh(), auth.force_refresh())
    # ensure_fresh rotates once; force_refresh always rotates — but never
    # concurrently, so no token is ever presented twice.
    presented = [b.get("refreshToken") for u, b in session.posts if "do_refresh" in u]
    assert len(presented) == len(set(presented)), f"token reused: {presented}"


# ---------------------------------------------------------------------------
# Envelope handling — HTTP 200 with a failure body
# ---------------------------------------------------------------------------


async def test_rejected_login_raises_auth_error_not_keyerror() -> None:
    """A bad password answers 200 with no `data` — surface the server message."""
    session = _Session()
    session.responder = lambda url, body: _Resp({"code": "ACC001", "msg": "Incorrect password"})
    auth = _auth(session)

    with pytest.raises(RenogyAuthError, match="Incorrect password"):
        await auth.login("user@example.com", "wrong")


async def test_login_without_token_pair_raises() -> None:
    session = _Session()
    session.responder = lambda url, body: _Resp({"data": {"accessToken": _fresh()}})
    auth = _auth(session)

    with pytest.raises(RenogyAuthError, match="no token pair"):
        await auth.login("user@example.com", "pw")


async def test_failed_refresh_does_not_persist_a_dead_pair() -> None:
    """Storing a half-formed pair would kill the chain with no recovery path."""
    session = _Session()
    session.responder = lambda url, body: _Resp(
        {"code": "DMC400", "msg": "User data anomaly detected."}
    )
    auth = _auth(session, _tokens(_stale()))

    with pytest.raises(RenogyAuthError, match="User data anomaly"):
        await auth.ensure_fresh()
    assert auth.tokens.refresh_token == "R1", "the previous good token must survive"


async def test_refresh_missing_one_token_raises() -> None:
    session = _Session()
    session.responder = lambda url, body: _Resp({"data": {"accessToken": _fresh()}})
    auth = _auth(session, _tokens(_stale()))

    with pytest.raises(RenogyAuthError, match="no token pair"):
        await auth.ensure_fresh()
    assert auth.tokens.refresh_token == "R1"


# ---------------------------------------------------------------------------
# int64 DID handling
# ---------------------------------------------------------------------------


async def test_rtm_did_keeps_full_int64_precision() -> None:
    """Python decodes JSON ints at arbitrary precision — unlike JS float64.

    257470607149498369 must not come back as ...368.
    """
    session = _Session()
    session.responder = lambda url, body: _Resp(
        {"data": {"token": "rtm2", "did": 257470607149498369}}
    )
    auth = _auth(session, _tokens(_fresh()))

    _, did = await auth.refresh_rtm_token()
    assert did == "257470607149498369"


async def test_rtm_did_prefers_did_str() -> None:
    session = _Session()
    session.responder = lambda url, body: _Resp(
        {
            "data": {
                "token": "rtm2",
                "didStr": "262590739387514881",
                "did": 262590739387514881,
            }
        }
    )
    auth = _auth(session, _tokens(_fresh()))

    _, did = await auth.refresh_rtm_token()
    assert did == "262590739387514881"
