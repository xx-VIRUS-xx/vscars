import hashlib
import json
import re
from datetime import datetime
from typing import Any
from typing import List, Optional, Tuple


DEFAULT_POLICY = {
    "profile": "balanced",            # safe | balanced | power
    "require_approval": True,
    "block_destructive": True,
    "allow_network": True,
    "kill_switch": False,
    "allowed_command_prefixes": "",   # comma/newline separated
}

SENSITIVE_TOOLS = {
    "run_command", "git_command", "delete_file", "edit_file",
    "create_file", "create_project", "copilot_agent", "ask_agent", "open_terminal",
}

AGENT_TOOLS = {
    "run_command", "git_command", "delete_file", "edit_file",
    "create_file", "create_project", "copilot_agent", "ask_agent", "open_terminal",
}

_DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-rf\s+[/~]",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\(\)\{\s*:\|:&\s*\};:",
    r"\b>\s*/dev/sd",
    r"\bsudo\s+rm\b",
    r"\bchmod\s+777\s+/",
    r"\bcrontab\s+-[re]\b",
    r"\bpasswd\b",
    r"\buser(del|add)\b",
    r"\biptables\b|\bnftables\b",
    r"\bsystemctl\s+(stop|disable|mask)\s+ssh",
    r"\bshred\b|\bwipe\b",
    r"\bpkill\s+-9\s+-1\b",
    r">\s*/etc/passwd",
    r">\s*/etc/shadow",
]

_NETWORK_PATTERNS = [
    r"\bcurl\b", r"\bwget\b", r"\bnc\b", r"\bncat\b",
    r"\bssh\b", r"\bscp\b", r"\brsync\b",
]


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalize_policy_row(policy_row) -> dict:
    if not policy_row:
        return dict(DEFAULT_POLICY)
    return {
        "profile": policy_row.profile or "balanced",
        "require_approval": _as_bool(policy_row.require_approval, True),
        "block_destructive": _as_bool(policy_row.block_destructive, True),
        "allow_network": _as_bool(policy_row.allow_network, True),
        "kill_switch": _as_bool(policy_row.kill_switch, False),
        "allowed_command_prefixes": policy_row.allowed_command_prefixes or "",
    }


def apply_profile_defaults(policy: dict) -> dict:
    profile = (policy.get("profile") or "balanced").lower()
    merged = dict(DEFAULT_POLICY)

    if profile == "safe":
        merged.update({
            "profile": "safe",
            "require_approval": True,
            "block_destructive": True,
            "allow_network": False,
            "kill_switch": False,
        })
    elif profile == "power":
        merged.update({
            "profile": "power",
            "require_approval": False,
            "block_destructive": True,
            "allow_network": True,
            "kill_switch": False,
        })
    else:
        merged.update({
            "profile": "balanced",
            "require_approval": True,
            "block_destructive": True,
            "allow_network": True,
            "kill_switch": False,
        })

    # user overrides
    for key in merged.keys():
        if key in policy and policy[key] is not None:
            merged[key] = policy[key]

    return merged


def parse_allowed_prefixes(raw: str) -> List[str]:
    if not raw:
        return []
    parts = []
    for token in re.split(r"[,\n]", raw):
        t = token.strip()
        if t:
            parts.append(t)
    return parts


def get_command_for_tool(tool_name: str, params: dict) -> str:
    if tool_name == "run_command":
        return (params.get("command") or "").strip()
    if tool_name == "git_command":
        cmd = (params.get("command") or "").strip()
        if cmd.startswith("git "):
            cmd = cmd[4:]
        return f"git {cmd}".strip()
    return ""


def is_sensitive_request(tool_name: str, params: dict) -> Tuple[bool, str]:
    if tool_name in SENSITIVE_TOOLS:
        return True, "sensitive_tool"
    if tool_name in {"open_file", "read_file"} and (params.get("filepath") or ""):
        return True, "file_access"
    return False, "normal"


def evaluate_request(policy: dict, tool_name: str, params: dict) -> Tuple[bool, Optional[str], bool, str]:
    # returns: allowed, blocked_reason, sensitive, sensitivity_reason
    sensitive, sensitivity_reason = is_sensitive_request(tool_name, params)

    if _as_bool(policy.get("kill_switch"), False) and tool_name in AGENT_TOOLS:
        return False, "kill_switch_enabled", sensitive, sensitivity_reason

    cmd = get_command_for_tool(tool_name, params)

    if cmd and _as_bool(policy.get("block_destructive"), True):
        for pattern in _DESTRUCTIVE_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return False, "blocked_destructive_pattern", True, "command_destructive"

    if cmd and not _as_bool(policy.get("allow_network"), True):
        for pattern in _NETWORK_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return False, "network_command_blocked", True, "network_command"

    allowed_prefixes = parse_allowed_prefixes(policy.get("allowed_command_prefixes") or "")
    if cmd and allowed_prefixes:
        if not any(cmd.startswith(prefix) for prefix in allowed_prefixes):
            return False, "command_not_in_allowlist", True, "command_allowlist"

    return True, None, sensitive, sensitivity_reason


def request_fingerprint(user_id: int, tool_name: str, params: dict) -> str:
    payload = {
        "user_id": user_id,
        "tool": tool_name,
        "params": params,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
