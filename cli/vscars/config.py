"""
Local config for the vscars CLI.
Stored at ~/.vscars/config.json
"""
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".vscars"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "agent.log"
PID_FILE = CONFIG_DIR / "agent.pid"


def load() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
    CONFIG_FILE.chmod(0o600)


def get(key: str, default=None):
    return load().get(key, default)


def set_key(key: str, value) -> None:
    data = load()
    data[key] = value
    save(data)


def is_configured() -> bool:
    cfg = load()
    return bool(cfg.get("server_url") and cfg.get("machine_token") and cfg.get("machine_id"))
