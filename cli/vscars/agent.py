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
    from websockets.exceptions import ConnectionClosed
except ImportError:
    print("❌ Missing dependency: pip install 'websockets>=12.0'")
    sys.exit(1)

from vscars import config as cfg
from vscars import executor

log = logging.getLogger("vscars.agent")

PING_INTERVAL = 25       # seconds between keepalive pings
RECONNECT_DELAY_MIN = 3  # start backing off at 3s
RECONNECT_DELAY_MAX = 60 # cap at 60s


async def run_agent(server_url: str, token: str, machine_id: str, name: str):
    ws_url = (
        server_url.rstrip("/")
        .replace("http://", "ws://")
        .replace("https://", "wss://")
    )
    ws_url = f"{ws_url}/ws/agent/{token}"

    short_token = token[:8] + "…"
    log.info("Connecting to relay: %s", ws_url.replace(token, short_token))

    async with websockets.connect(ws_url, open_timeout=15, close_timeout=5) as ws:
        # First message should be the welcome frame
        raw = await asyncio.wait_for(ws.recv(), timeout=15)
        data = json.loads(raw)
        if data.get("type") == "connected":
            machine_name = data.get("name", name)
            log.info("✅ Connected — machine '%s' is online", machine_name)
            print(f"✅ Connected: {machine_name}")
            print("   Relay is live. Waiting for commands from the app… (Ctrl+C to stop)")
        else:
            log.warning("Unexpected first message: %s", data)

        # Background keepalive ping loop
        async def ping_loop():
            while True:
                await asyncio.sleep(PING_INTERVAL)
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                except Exception:
                    return  # connection gone — outer loop will reconnect

        asyncio.ensure_future(ping_loop())

        # Main message loop
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type")

            if msg_type == "pong":
                continue

            if msg_type == "tool_call":
                call_id = msg.get("call_id")
                tool_name = msg.get("tool")
                params = msg.get("params", {})
                log.info("→ tool_call %s  id=%s", tool_name, call_id)

                result = executor.execute(tool_name, params)
                result["call_id"] = call_id
                result["type"] = "tool_result"

                await ws.send(json.dumps(result))
                log.info("← result  id=%s  success=%s", call_id, result.get("success"))


async def _run_with_reconnect(server_url: str, token: str, machine_id: str, name: str):
    delay = RECONNECT_DELAY_MIN
    while True:
        try:
            await run_agent(server_url, token, machine_id, name)
            # clean exit (e.g. KeyboardInterrupt caught inside run_agent)
            break
        except KeyboardInterrupt:
            print("\n👋 Stopped.")
            break
        except ConnectionClosed as e:
            log.warning("Connection closed: %s — reconnecting in %ds", e, delay)
            print(f"⚠  Connection closed. Reconnecting in {delay}s…")
        except OSError as e:
            log.warning("Network error: %s — reconnecting in %ds", e, delay)
            print(f"⚠  Network error ({e}). Reconnecting in {delay}s…")
        except Exception as e:
            log.warning("Unexpected error: %s — reconnecting in %ds", e, delay)
            print(f"⚠  Error: {e}. Reconnecting in {delay}s…")

        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_DELAY_MAX)  # exponential backoff


def start():
    """Entry point for `vscars start` — runs the agent in the foreground."""
    if not cfg.is_configured():
        print("❌ Not configured. Run `vscars init` first.")
        sys.exit(1)

    c = cfg.load()
    server_url = c.get("server_url")
    token = c.get("machine_token")
    machine_id = c.get("machine_id")
    name = c.get("machine_name", platform.node())

    if not server_url or not token or not machine_id:
        print("❌ Config is incomplete. Run `vscars init` again.")
        sys.exit(1)

    # Set up logging — both file and stdout
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(cfg.LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Write PID so `vscars stop` can find us
    cfg.PID_FILE.write_text(str(os.getpid()))

    def _cleanup(sig, frame):
        cfg.PID_FILE.unlink(missing_ok=True)
        print("\n👋 Agent stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _cleanup)
    signal.signal(signal.SIGTERM, _cleanup)

    print(f"VSCARS agent starting — server: {server_url}")
    print(f"Machine: {name} ({machine_id[:8]}…)")
    print(f"Logs: {cfg.LOG_FILE}")
    print()

    try:
        asyncio.run(_run_with_reconnect(server_url, token, machine_id, name))
    finally:
        cfg.PID_FILE.unlink(missing_ok=True)
