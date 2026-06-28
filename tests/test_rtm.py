"""Tests for the Renogy RTM client's unexpected-disconnect signaling.

Regression coverage for the review finding that `_reader()` exiting (socket
closed by the peer) never notified anything, so the coordinator's
auto-reconnect logic was permanently orphaned.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.renogy_gateway.api.rtm import RenogyRTM


class _FakeMsg:
    def __init__(self, msg_type: aiohttp.WSMsgType) -> None:
        self.type = msg_type
        self.data = None


class _ClosingWS:
    """A fake WS that delivers one CLOSE frame then ends — simulates the peer dropping the socket."""

    def __init__(self) -> None:
        self.closed = False
        self._sent = False

    def __aiter__(self) -> "_ClosingWS":
        return self

    async def __anext__(self) -> _FakeMsg:
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        return _FakeMsg(aiohttp.WSMsgType.CLOSE)


class _BlockingWS:
    """A fake WS whose iterator never yields until cancelled — simulates an open connection."""

    def __init__(self) -> None:
        self.closed = False
        self.close = AsyncMock()

    def __aiter__(self) -> "_BlockingWS":
        return self

    async def __anext__(self) -> _FakeMsg:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.fixture
def rtm() -> RenogyRTM:
    return RenogyRTM(MagicMock(), MagicMock())


async def test_unexpected_reader_exit_fires_disconnect_callback(rtm: RenogyRTM) -> None:
    """The reader exiting on its own (peer closed the socket) must notify the callback."""
    fired = []
    rtm.set_unexpected_disconnect_callback(lambda: fired.append(True))
    rtm._ws = _ClosingWS()

    await rtm._reader()
    await asyncio.sleep(0)  # let the call_soon-scheduled callback run

    assert fired == [True]
    assert rtm._connected is False


async def test_clean_disconnect_suppresses_callback(rtm: RenogyRTM) -> None:
    """An intentional disconnect() must not trigger the unexpected-disconnect callback."""
    fired = []
    rtm.set_unexpected_disconnect_callback(lambda: fired.append(True))
    rtm._ws = _BlockingWS()
    rtm._connected = True
    rtm._reader_task = asyncio.ensure_future(rtm._reader())
    await asyncio.sleep(0)  # let the reader task start blocking on the iterator

    await rtm.disconnect()
    await asyncio.sleep(0)

    assert fired == []


async def test_connect_resets_closing_flag_for_next_disconnect(rtm: RenogyRTM) -> None:
    """After a clean disconnect, a fresh connect() must re-arm unexpected-disconnect detection."""
    rtm._closing = True

    rtm._auth.refresh_rtm_token = AsyncMock(side_effect=RuntimeError("stop before ws"))
    with pytest.raises(RuntimeError):
        await rtm.connect()

    assert rtm._closing is False
