"""Renogy RTM — real-time device telemetry and control over WebSocket.

Custom MQTT-style pub/sub protocol. Frames are JSON keyed by `op`:
  op 9 / 8   connect / connect-ack
  op 2 → 3   read a value (response carries wopid matching opid)
  op 4        subscribe (telemetry then streams as op 7)
  op 7        telemetry push {sp, data}
  op 6        RPC method call
  op 1        WRITE / SET — the control path
"""

import asyncio
from collections.abc import Callable
import contextlib
import json
import logging
from typing import Any

import aiohttp

from .auth import RenogyAuth, RenogyConnectionError

_LOGGER = logging.getLogger(__name__)

RTM_URL = "wss://gateway.renogy.com/rtm/ws"
_RPC_TIMEOUT = 10.0
_RPC_RETRIES = 3
_CONNECT_TIMEOUT = 10.0

TelemetryCallback = Callable[[str, Any], None]


class RenogyRTMError(Exception):
    """Raised when the RTM WebSocket encounters a protocol error."""


class RenogyRTM:
    """Async WebSocket client for the Renogy RTM protocol.

    Call connect() to open the WebSocket.
    Register telemetry handlers with on_push(sp, callback).
    Use read(), subscribe(), write(), and rpc() for protocol operations.
    """

    def __init__(self, session: aiohttp.ClientSession, auth: RenogyAuth) -> None:
        """Initialize the RTM client with an aiohttp session and auth handler."""
        self._session = session
        self._auth = auth
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._opid = 2000
        self._pending: dict[int, asyncio.Future] = {}
        self._subscriptions: dict[str, list[TelemetryCallback]] = {}
        self._reader_task: asyncio.Task | None = None
        self._connected = False
        self._closing = False
        self._global_dispatcher: TelemetryCallback | None = None
        self._on_unexpected_disconnect: Callable[[], None] | None = None

    def set_unexpected_disconnect_callback(self, fn: Callable[[], None] | None) -> None:
        """Set a callback fired when the reader exits without disconnect() having been called."""
        self._on_unexpected_disconnect = fn

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the WebSocket and send the connect frame (op-9).

        Mirrors the app flow: fetch RTM token → upgrade WS → retry once on 403.
        Raises RenogyConnectionError on failure.
        """
        self._closing = False
        rtm_token, rtm_did = await self._auth.refresh_rtm_token()
        self._ws = await self._open_ws(rtm_token)

        await self._send(
            {
                "op": 9,
                "data": {
                    "did": int(rtm_did),
                    "expiryInterval": -1,
                    "cleanStart": True,
                    "nodeType": 4,
                },
            }
        )

        # Wait for connect-ack (op-8) with timeout
        try:
            ack_raw = await asyncio.wait_for(
                self._ws.receive(), timeout=_CONNECT_TIMEOUT
            )
        except TimeoutError as err:
            raise RenogyConnectionError("RTM connect-ack timed out") from err

        if ack_raw.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSED,
            aiohttp.WSMsgType.ERROR,
        ):
            raise RenogyConnectionError(
                f"RTM WebSocket closed before connect-ack: {ack_raw}"
            )

        ack = json.loads(ack_raw.data)
        if ack.get("op") != 8 or ack.get("code") != 0:
            raise RenogyConnectionError(
                f"RTM connect-ack failed (code {ack.get('code')})"
            )

        self._connected = True
        self._reader_task = asyncio.ensure_future(self._reader())
        _LOGGER.debug("RTM connected (did=%s)", rtm_did)

    async def _open_ws(self, rtm_token: str) -> aiohttp.ClientWebSocketResponse:
        """Open the WebSocket upgrade, retrying once on 403."""
        headers = {"device-token": rtm_token, "Origin": "https://gateway.renogy.com"}
        try:
            ws = await self._session.ws_connect(
                RTM_URL,
                headers=headers,
                heartbeat=30,
                timeout=aiohttp.ClientWSTimeout(ws_close=_CONNECT_TIMEOUT),
            )
        except aiohttp.WSServerHandshakeError as err:
            if err.status != 403:
                raise RenogyConnectionError(f"RTM WS handshake failed: {err}") from err
            # 403 = stale session; rotate token and retry once
            rtm_token, _ = await self._auth.refresh_rtm_token()
            headers["device-token"] = rtm_token
            try:
                ws = await self._session.ws_connect(
                    RTM_URL,
                    headers=headers,
                    heartbeat=30,
                    timeout=aiohttp.ClientWSTimeout(ws_close=_CONNECT_TIMEOUT),
                )
            except aiohttp.ClientError as retry_err:
                raise RenogyConnectionError(
                    f"RTM WS retry failed: {retry_err}"
                ) from retry_err
        except aiohttp.ClientError as err:
            raise RenogyConnectionError(f"RTM WS connection failed: {err}") from err
        return ws

    async def disconnect(self) -> None:
        """Close the WebSocket connection cleanly."""
        self._closing = True
        self._connected = False
        if self._reader_task:
            self._reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader_task
            self._reader_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        # Reject all pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RenogyRTMError("RTM disconnected"))
        self._pending.clear()

    # ------------------------------------------------------------------
    # Frame I/O
    # ------------------------------------------------------------------

    def _next_opid(self) -> int:
        self._opid += 1
        return self._opid

    async def _send(self, frame: dict) -> None:
        if self._ws is None or self._ws.closed:
            raise RenogyRTMError("RTM not connected")
        await self._ws.send_str(json.dumps(frame))

    async def _call(self, frame: dict, timeout: float = _RPC_TIMEOUT) -> dict:
        """Send a correlated frame and await its response."""
        opid = self._next_opid()
        frame["opid"] = opid
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[opid] = fut
        await self._send(frame)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except TimeoutError:
            self._pending.pop(opid, None)
            raise
        finally:
            self._pending.pop(opid, None)

    async def _reader(self) -> None:
        """Background task that reads frames from the WebSocket."""
        assert self._ws is not None
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "ping":
                        await self._ws.send_str("pong")
                        continue
                    await self._dispatch(msg.data)
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                ):
                    break
        except asyncio.CancelledError:
            pass
        except Exception:
            _LOGGER.exception("RTM reader error")
        finally:
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(RenogyRTMError("RTM reader closed"))
            self._pending.clear()
            if not self._closing and self._on_unexpected_disconnect is not None:
                asyncio.get_running_loop().call_soon(self._on_unexpected_disconnect)

    async def _dispatch(self, raw: str) -> None:
        """Process one received JSON frame."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        op = msg.get("op")
        wopid = msg.get("wopid")

        # RPC responses can arrive as op-7 frames carrying a wopid, so resolve
        # pending request-response correlation before treating op-7 as telemetry.
        if wopid is not None and wopid in self._pending:
            fut = self._pending[wopid]
            if not fut.done():
                fut.set_result(msg)
            if op != 7:
                return

        if op == 7:
            sp = msg.get("sp")
            data = msg.get("data")
            if sp:
                self._fire_callbacks(sp, data)

    def set_telemetry_dispatcher(self, fn: TelemetryCallback | None) -> None:
        """Set a global telemetry dispatcher called for every op-7 push."""
        self._global_dispatcher = fn

    def _fire_callbacks(self, sp: str, value: Any) -> None:
        if self._global_dispatcher is not None:
            self._global_dispatcher(sp, value)
            return
        for cb in self._subscriptions.get(sp, []):
            try:
                cb(sp, value)
            except Exception:
                _LOGGER.exception("RTM callback error for sp=%s", sp)

    # ------------------------------------------------------------------
    # Public protocol operations
    # ------------------------------------------------------------------

    async def read(self, sp: str) -> Any:
        """Read current value of a field (op-2 → op-3)."""
        resp = await self._call({"op": 2, "sp": sp})
        return resp.get("data")

    async def subscribe(self, sp: str) -> None:
        """Subscribe to a topic (op-4); telemetry arrives via registered callbacks."""
        await self._call({"op": 4, "sp": sp, "ack": True, "qos": 0})

    async def rpc(self, sp: str, data: Any, *, retries: int = _RPC_RETRIES) -> Any:
        """Call an RPC method (op-6) with retry on timeout."""
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                resp = await self._call(
                    {"op": 6, "sp": sp, "data": data, "ack": True, "qos": 1}
                )
                return resp.get("data")
            except TimeoutError as err:
                last_err = err
                _LOGGER.debug(
                    "RPC %s timeout (attempt %d/%d)", sp, attempt + 1, retries
                )
                await asyncio.sleep(0.3 * (attempt + 1))
        raise RenogyRTMError(f"RPC {sp} failed after {retries} attempts") from last_err

    async def write(self, sp: str, value: Any) -> dict:
        """Write a value to a controllable field (op-1).

        Returns the ACK frame. code=0 is explicit success; code=14 means the
        command was queued — wait for an op-7 push rather than reading back.
        """
        return await self._call(
            {"op": 1, "sp": sp, "data": value, "ack": True, "qos": 1}
        )

    async def run_scene(self, gateway_did: str, scene_id: int) -> dict:
        """Execute a Manual scene (op-6 RPC `<gwDid>/scene.run {sceneId}`).

        PROTOCOL.md §8.3: runs a batch of writes to physical circuits.
        Returns the ACK frame (code=0 success, code=14 queued).
        """
        sp = f"{gateway_did}/scene.run"
        return await self._call(
            {"op": 6, "sp": sp, "data": {"sceneId": scene_id}, "ack": True, "qos": 1}
        )

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def register_callback(self, sp: str, callback: TelemetryCallback) -> None:
        """Register a callback to receive telemetry pushes for a specific sp."""
        self._subscriptions.setdefault(sp, []).append(callback)

    def unregister_callback(self, sp: str, callback: TelemetryCallback) -> None:
        """Remove a previously registered callback."""
        callbacks = self._subscriptions.get(sp, [])
        with contextlib.suppress(ValueError):
            callbacks.remove(callback)
        if not callbacks:
            self._subscriptions.pop(sp, None)
