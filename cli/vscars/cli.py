"""
vscars CLI entry point.

Commands:
  vscars init      Register this machine with your VSCARS account
  vscars start     Start the agent (connects your machine to the relay)
  vscars stop      Stop a background agent process
  vscars status    Show current config and connection status
  vscars logs      Tail the agent log file
  vscars workspace Set the default workspace directory
"""
import argparse
import json
import os
import platform
import sys
import uuid

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from vscars import config as cfg, __version__


# ─── helpers ──────────────────────────────────────────────────────────────────

def _req(method: str, url: str, **kwargs):
    if requests is None:
        print("❌ Missing dependency: pip install requests")
        sys.exit(1)
    try:
        r = getattr(requests, method)(url, timeout=15, **kwargs)
        return r
    except requests.exceptions.ConnectionError:
        print(f"❌ Cannot reach server at {url}. Is it running?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Request failed: {e}")
        sys.exit(1)


# ─── commands ─────────────────────────────────────────────────────────────────

DEFAULT_SERVER = "https://vscars.latenightstack.com"


def cmd_init(args):
    """Link this machine to your VSCARS account using your API key."""
    print(f"━━━ VSCARS Init v{__version__} ━━━")
    print()

    existing = cfg.load()

    # Server URL (advanced — most users keep the default)
    default_url = existing.get("server_url", DEFAULT_SERVER)
    if args.server:
        server_url = args.server.rstrip("/")
    else:
        answer = input(f"Server URL [{default_url}]: ").strip()
        server_url = (answer or default_url).rstrip("/")

    # API key
    existing_key = existing.get("api_key", "")
    if getattr(args, "api_key", None):
        api_key = args.api_key
    else:
        print()
        print("Your API key is in the app under Settings → API Key → Generate.")
        print(f"  → {server_url}/app")
        print()
        if existing_key:
            print(f"  (current key: {existing_key[:12]}…  press Enter to keep)")
        api_key = input("API Key: ").strip()
        if not api_key and existing_key:
            api_key = existing_key
    if not api_key:
        print("❌ API key required. Get yours at: " + server_url)
        sys.exit(1)

    # Validate key against server
    print()
    print("Validating API key…")
    r = _req("get", f"{server_url}/api/auth/api-key", headers={"X-VSCARS-Key": api_key})
    if r.status_code == 401:
        print("❌ Invalid API key. Check the key in your VSCARS dashboard.")
        sys.exit(1)
    if r.status_code != 200:
        print(f"❌ Server error ({r.status_code}): {r.text}")
        sys.exit(1)

    key_info = r.json()
    print(f"✅ API key valid  (plan: {key_info.get('plan', 'beta')})")

    # Machine details
    machine_id = existing.get("machine_id") or str(uuid.uuid4())
    default_name = existing.get("machine_name") or platform.node()
    if getattr(args, "machine_name", None):
        name = args.machine_name
    else:
        name = input(f"\nMachine name [{default_name}]: ").strip() or default_name

    # Register machine
    print("Registering machine…")
    r = _req("post", f"{server_url}/api/machines/register",
             headers={"X-VSCARS-Key": api_key},
             json={
                 "machine_id": machine_id,
                 "name": name,
                 "hostname": platform.node(),
                 "os_info": f"{platform.system()} {platform.release()}",
             })

    if r.status_code == 403:
        detail = r.json().get("detail", {})
        msg = detail.get("message", str(detail)) if isinstance(detail, dict) else str(detail)
        print(f"❌ {msg}")
        print(f"   Setup guide: {server_url}/setup")
        sys.exit(1)

    if r.status_code != 200:
        print(f"❌ Registration failed: {r.text}")
        sys.exit(1)

    reg = r.json()
    machine_token = reg["token"]

    # Default workspace = directory where `vscars init` was run
    default_workspace = os.path.realpath(os.getcwd())
    ws_file = cfg.CONFIG_DIR / "workspace.txt"

    # Save config
    cfg.save({
        "server_url": server_url,
        "api_key": api_key,
        "machine_id": machine_id,
        "machine_name": name,
        "machine_token": machine_token,
        "workspace": default_workspace,
    })

    # Write workspace file for executor to pick up immediately
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ws_file.write_text(default_workspace)

    print(f"\n✅ Machine '{name}' registered!")
    print(f"   Default workspace: {default_workspace}")
    print(f"   Config: {cfg.CONFIG_FILE}")
    print()
    print("▶  Run `vscars start` to connect your machine.")


def cmd_start(args):
    """Start the agent (runs in foreground; use a service manager for background)."""
    import shutil

    # --- Auto-setup prompt ---
    missing = []
    if not shutil.which("claude"):
        missing.append("Claude Code  (npm install -g @anthropic-ai/claude-code)")
    if not shutil.which("copilot"):
        missing.append("Copilot CLI  (npm install -g @github/copilot)")
    if not shutil.which("codex") and not shutil.which("codex-cli"):
        missing.append("Codex CLI    (npm install -g @openai/codex)")

    # Detect locally-running inference servers (Ollama, LM Studio, llama.cpp)
    local_agents = []
    for port, label in [(11434, "Ollama :11434"), (1234, "LM Studio :1234"), (8080, "llama.cpp :8080")]:
        import socket as _sock
        try:
            with _sock.create_connection(("127.0.0.1", port), timeout=0.5):
                local_agents.append(label)
        except OSError:
            pass

    if local_agents:
        print(f"🤖 Local inference detected: {', '.join(local_agents)}")

    if missing:
        print()
        print("⚠  Missing AI agents:")
        for m in missing:
            print(f"   • {m}")
        print()
        try:
            answer = input("Auto-install missing agents now? [Y/n]: ").strip().lower()
        except EOFError:
            answer = "n"
        if answer in ("", "y", "yes"):
            _run_agent_setup()
        else:
            print("Skipping — you can run `vscars setup` later.")
    print()

    from vscars.agent import start
    start()


def _run_agent_setup():
    """Install missing AI agents non-interactively."""
    import shutil, subprocess, platform as _platform
    sys_name = _platform.system()

    # Claude Code
    if not shutil.which("claude"):
        if shutil.which("npm"):
            print("⬇  Installing Claude Code…")
            r = subprocess.run(["npm", "install", "-g", "@anthropic-ai/claude-code"],
                               capture_output=False, timeout=120)
            print("✅ Claude Code installed." if r.returncode == 0 else "❌ Claude Code install failed — check npm.")
        else:
            print("⚠  npm not found — install Node.js first to get Claude Code: https://nodejs.org")

    # Copilot CLI
    if not shutil.which("copilot"):
        if shutil.which("npm"):
            print("⬇  Installing Copilot CLI…")
            r = subprocess.run(["npm", "install", "-g", "@github/copilot"],
                               capture_output=False, timeout=120)
            print("✅ Copilot CLI installed." if r.returncode == 0 else "❌ Copilot CLI install failed.")
        else:
            print("⚠  npm not found — install Node.js to get Copilot CLI: https://nodejs.org")

    # Codex CLI
    if not shutil.which("codex") and not shutil.which("codex-cli"):
        if shutil.which("npm"):
            print("⬇  Installing Codex CLI…")
            r = subprocess.run(["npm", "install", "-g", "@openai/codex"],
                               capture_output=False, timeout=120)
            print("✅ Codex CLI installed." if r.returncode == 0 else "❌ Codex CLI install failed.")


def cmd_stop(args):
    """Send SIGTERM to a running agent."""
    if not cfg.PID_FILE.exists():
        print("No agent PID file found. Is the agent running?")
        return
    pid = int(cfg.PID_FILE.read_text().strip())
    try:
        os.kill(pid, 15)  # SIGTERM
        cfg.PID_FILE.unlink(missing_ok=True)
        print(f"✅ Sent stop signal to agent (PID {pid})")
    except ProcessLookupError:
        print("Agent process not found — it may have already stopped.")
        cfg.PID_FILE.unlink(missing_ok=True)
    except Exception as e:
        print(f"❌ Error: {e}")


def cmd_status(args):
    """Show config and connection status."""
    print(f"━━━ VSCARS Status v{__version__} ━━━")

    if not cfg.is_configured():
        print("Not configured. Run `vscars init`.")
        return

    c = cfg.load()
    print(f"Server    : {c.get('server_url')}")
    print(f"Machine   : {c.get('machine_name')} ({c.get('machine_id', '')[:8]}…)")
    print(f"Config    : {cfg.CONFIG_FILE}")
    print(f"Log file  : {cfg.LOG_FILE}")

    # Check if agent PID is alive
    if cfg.PID_FILE.exists():
        pid = int(cfg.PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)
            print(f"Agent     : Running (PID {pid})")
        except ProcessLookupError:
            print("Agent     : Not running (stale PID file)")
    else:
        print("Agent     : Not running")

    # Ping server
    server_url = c["server_url"]
    print(f"\nChecking server…")
    try:
        r = _req("get", f"{server_url}/api/health")
        if r.status_code == 200:
            print(f"Server    : ✅ Online ({server_url})")
        else:
            print(f"Server    : ⚠️  Responded with {r.status_code}")
    except SystemExit:
        print("Server    : ❌ Unreachable")


def cmd_logs(args):
    """Tail the agent log file."""
    if not cfg.LOG_FILE.exists():
        print("No log file found. Has the agent run yet?")
        return
    lines = args.lines or 50
    content = cfg.LOG_FILE.read_text().splitlines()
    for line in content[-lines:]:
        print(line)


def cmd_workspace(args):
    """Set the default workspace directory for tool execution."""
    path = os.path.realpath(os.path.expanduser(args.path))
    if not os.path.isdir(path):
        print(f"❌ Directory not found: {path}")
        sys.exit(1)
    ws_file = cfg.CONFIG_DIR / "workspace.txt"
    cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ws_file.write_text(path)
    print(f"✅ Workspace set to: {path}")


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="vscars",
        description="VSCARS — connect your machine to the VSCARS platform",
    )
    parser.add_argument("--version", action="version", version=f"vscars {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Register this machine with your account")
    p_init.add_argument("--server", default=None, help=f"Server URL (default: {DEFAULT_SERVER})")
    p_init.add_argument("--api-key", default=None, dest="api_key", help="Your VSCARS API key")
    p_init.add_argument("--name", default=None, dest="machine_name", help="Machine name (skips prompt)")
    sub.add_parser("start", help="Start the agent (connects to relay)")
    sub.add_parser("stop", help="Stop a running agent")
    sub.add_parser("status", help="Show status")

    p_logs = sub.add_parser("logs", help="Show agent logs")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Number of lines")

    p_ws = sub.add_parser("workspace", help="Set default workspace path")
    p_ws.add_argument("path", help="Absolute or ~ path to workspace directory")

    sub.add_parser("setup", help="Detect and install missing AI agents (Claude Code, gh Copilot)")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "start": cmd_start,
        "stop": cmd_stop,
        "status": cmd_status,
        "logs": cmd_logs,
        "workspace": cmd_workspace,
        "setup": lambda _: _run_agent_setup(),
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
