"""Tests for the Renogy RTM client's unexpected-disconnect signaling.

Regression coverage for the review finding that `_reader()` exiting (socket
closed by the peer) never notified anything, so the coordinator's
auto-reconnect logic was permanently orphaned.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.renogy_gateway.api.auth import RenogyConnectionError
from custom_components.renogy_gateway.api.rtm import RenogyRTM


class _FakeMsg:
    def __init__(self, msg_type: aiohttp.WSMsgType) -> None:
        self.type = msg_type
        self.data = None


class _ClosingWS:
    """A fake WS that delivers one CLOSE frame then ends.

    Simulates the peer dropping the socket.
    """

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


# ---------------------------------------------------------------------------
# Connect-ack framing
# ---------------------------------------------------------------------------


class _ScriptedWS:
    """A fake WS that yields a scripted list of frames from receive()."""

    def __init__(self, frames: list) -> None:
        self._frames = list(frames)
        self.closed = False
        self.sent: list[str] = []
        self.close = AsyncMock()

    async def receive(self) -> "_TextMsg":
        if not self._frames:
            await asyncio.Event().wait()
        return self._frames.pop(0)

    async def send_str(self, data: str) -> None:
        self.sent.append(data)

    def __aiter__(self) -> "_ScriptedWS":
        return self

    async def __anext__(self) -> "_TextMsg":
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _TextMsg:
    def __init__(self, data: str) -> None:
        self.type = aiohttp.WSMsgType.TEXT
        self.data = data


def _ack(**over) -> _TextMsg:
    frame = {"op": 8, "sop": 9, "code": 0, "data": {"token": "session.jwt"}}
    frame.update(over)
    return _TextMsg(json.dumps(frame))


async def _connect_with(frames: list) -> _ScriptedWS:
    """Run RenogyRTM.connect() against a scripted socket."""
    ws = _ScriptedWS(frames)
    auth = MagicMock()
    auth.refresh_rtm_token = AsyncMock(return_value=("tok", "257470607149498369"))
    rtm = RenogyRTM(MagicMock(), auth)
    rtm._open_ws = AsyncMock(return_value=ws)
    try:
        await rtm.connect()
    finally:
        if rtm._reader_task:
            rtm._reader_task.cancel()
    return ws


async def test_connect_accepts_the_ack() -> None:
    ws = await _connect_with([_ack()])
    sent = json.loads(ws.sent[0])
    assert sent["op"] == 9
    # int64 DID must survive as an exact integer.
    assert sent["data"]["did"] == 257470607149498369


async def test_connect_survives_a_ping_before_the_ack() -> None:
    """The gateway sends bare `ping` text frames unprompted.

    json.loads("ping") raises JSONDecodeError, which is not an
    aiohttp.ClientError — so it used to escape connect() as an unexpected
    exception instead of being skipped.
    """
    ws = await _connect_with([_TextMsg("ping"), _ack()])
    assert "pong" in ws.sent, "a ping before the ack must still be answered"


async def test_connect_skips_stray_frames_before_the_ack() -> None:
    stray = _TextMsg(json.dumps({"op": 7, "sp": "1/thing.title", "data": "x"}))
    await _connect_with([stray, _ack()])


async def test_connect_ignores_a_non_connect_op8_ack() -> None:
    """op-8 is the GENERIC ack; a subscribe ack (sop 4, with wopid) is not it."""
    sub_ack = _TextMsg(json.dumps({"op": 8, "sop": 4, "code": 0, "wopid": 42}))
    await _connect_with([sub_ack, _ack()])


async def test_connect_accepts_an_ack_without_sop() -> None:
    """Fallback: the connect-ack is the only op-8 frame carrying no wopid."""
    legacy = _TextMsg(json.dumps({"op": 8, "code": 0, "data": {"token": "t"}}))
    await _connect_with([legacy])


async def test_connect_rejects_a_nonzero_ack_code() -> None:
    with pytest.raises(RenogyConnectionError, match="code 3"):
        await _connect_with([_ack(code=3)])
