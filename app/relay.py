"""
WebSocket relay manager.

Each registered user runs `vscars start` on their own machine. That opens a
persistent WebSocket to /ws/agent/{token}. When the user issues a tool call from
the web UI, the server relays it to their machine and awaits the result.
The server's own filesystem is never touched for regular users.
"""

import asyncio
import uuid
import logging
from fastapi import WebSocket

log = logging.getLogger(__name__)

# user_id -> {machine_id -> WebSocket}
_connections: dict[int, dict[str, WebSocket]] = {}

# call_id -> asyncio.Future  (HTTP handler awaits this while WS handler resolves it)
_pending: dict[str, "asyncio.Future[dict]"] = {}


def register(user_id: int, machine_id: str, ws: WebSocket) -> None:
    if user_id not in _connections:
        _connections[user_id] = {}
    _connections[user_id][machine_id] = ws
    log.info("relay: machine %s connected for user %d", machine_id, user_id)


def unregister(user_id: int, machine_id: str) -> None:
    if user_id in _connections:
        _connections[user_id].pop(machine_id, None)
        if not _connections[user_id]:
            del _connections[user_id]
    log.info("relay: machine %s disconnected for user %d", machine_id, user_id)


def is_connected(user_id: int) -> bool:
    return bool(_connections.get(user_id))


def get_connected_machines(user_id: int) -> list[str]:
    return list(_connections.get(user_id, {}).keys())


async def call_tool(
    user_id: int,
    machine_id: str | None,
    tool_name: str,
    params: dict,
    timeout: float = 90.0,
) -> dict:
    """Forward a tool call to the user's connected machine and await the result.

    Raises ConnectionError if no machine is connected.
    Raises asyncio.TimeoutError if the machine doesn't respond in time.
    """
    machines = _connections.get(user_id, {})
    if not machines:
        raise ConnectionError(
            "No machine connected. Run `vscars start` on your laptop first."
        )

    if machine_id:
        ws = machines.get(machine_id)
        if not ws:
            raise ConnectionError(
                f"Machine '{machine_id}' is not currently connected."
            )
    else:
        # Use whichever machine is connected (first one)
        ws = next(iter(machines.values()))

    call_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[dict] = loop.create_future()
    _pending[call_id] = fut

    try:
        await ws.send_json({
            "type": "tool_call",
            "call_id": call_id,
            "tool": tool_name,
            "params": params,
        })
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        _pending.pop(call_id, None)


def resolve_call(call_id: str, result: dict) -> None:
    """Called by the WebSocket handler when the machine sends a tool_result."""
    fut = _pending.get(call_id)
    if fut and not fut.done():
        fut.set_result(result)
