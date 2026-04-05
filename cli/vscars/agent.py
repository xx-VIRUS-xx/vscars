"""
vscars agent — persistent WebSocket client that runs on the user's machine.

Started by `vscars start`. Connects to the relay server, listens for tool
calls, executes them locally, and sends results back.
"""
import asyncio
import json
import logging
import os
import platform
import signal
import sys
import time
from pathlib import Path

try:
    import websockets
except ImportError:
    print("❌ Missing dependency: pip install websockets")
    sys.exit(1)

from vscars import config as cfg
from vscars import executor

log = logging.getLogger("vscars.agent")

PING_INTERVAL = 25  # seconds
RECONNECT_DELAY = 5  # seconds between reconnect attempts


async def run_agent(server_url: str, token: str, machine_id: str, name: str):
    ws_url = server_url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/ws/agent/{token}"

    log.info("Connecting to %s …", ws_url.replace(token, token[:8] + "…"))

    async with websockets.connect(
        ws_url,
        ping_interval=PING_INTERVAL,
        ping_timeout=10,
        close_timeout=5,
    ) as ws:
        msg = await ws.recv()
        data = json.loads(msg)
        if data.get("type") == "connected":
            log.info("✅ Connected — machine '%s' is online", data.get("name", name))
            print(f"✅ VSCARS agent connected: {data.get('name', name)}")
            print("   Waiting for tool calls… (Ctrl+C to stop)")

        async def send_ping():
            while True:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    break

        asyncio.ensure_future(send_ping())

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            if msg.get("type") == "pong":
                continue

            if msg.get("type") == "tool_call":
                call_id = msg.get("call_id")
                tool_name = msg.get("tool")
                params = msg.get("params", {})
                log.info("→ tool_call %s %s", tool_name, call_id)

                result = executor.execute(tool_name, params)
                result["call_id"] = call_id
                result["type"] = "tool_result"

                await ws.send(json.dumps(result))
                log.info("← result %s success=%s", call_id, result.get("success"))


async def _run_with_reconnect(server_url: str, token: str, machine_id: str, name: str):
    while True:
        try:
            await run_agent(server_url, token, machine_id, name)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            log.warning("Disconnected: %s — reconnecting in %ds", e, RECONNECT_DELAY)
            print(f"⚠️  Disconnected ({e}). Reconnecting in {RECONNECT_DELAY}s…")
            await asyncio.sleep(RECONNECT_DELAY)


def start():
    """Entry point for `vscars start` — runs the agent in the foreground."""
    if not cfg.is_configured():
        print("❌ Not configured. Run `vscars init` first.")
        sys.exit(1)

    c = cfg.load()
    server_url = c["server_url"]
    token = c["machine_token"]
    machine_id = c["machine_id"]
    name = c.get("machine_name", platform.node())

    log_path = cfg.LOG_FILE
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Write PID file
    cfg.PID_FILE.write_text(str(os.getpid()))

    def _cleanup(sig, frame):
        cfg.PID_FILE.unlink(missing_ok=True)
        print("\n👋 Agent stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    try:
        asyncio.run(_run_with_reconnect(server_url, token, machine_id, name))
    finally:
        cfg.PID_FILE.unlink(missing_ok=True)
