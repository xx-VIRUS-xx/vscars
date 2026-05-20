"""
Local tool executor — runs on the user's own machine.
Called by the agent when it receives a tool_call from the relay server.

This mirrors the server's tools.py logic but runs entirely locally
against the user's own filesystem.
"""
import os
import subprocess
import platform
import shlex
import re
from pathlib import Path
from typing import Optional


COMMAND_TIMEOUT = int(os.getenv("VSCARS_COMMAND_TIMEOUT", "30"))
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _get_workspace() -> str:
    ws_file = os.path.expanduser("~/.vscars/workspace.txt")
    if os.path.exists(ws_file):
        ws = Path(ws_file).read_text().strip()
        if ws and os.path.isdir(ws):
            return ws
    return os.path.expanduser("~")


def _resolve(path: str) -> str:
    workspace = os.path.realpath(_get_workspace())
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(workspace, path))
    # Allow workspace itself, anything inside it, or /tmp
    if resolved == workspace or resolved.startswith(workspace + os.sep):
        return resolved
    if resolved.startswith("/tmp/") or resolved == "/tmp":
        return resolved
    raise ValueError(f"Access denied: '{path}' is outside the workspace ({workspace})")


# ─── Tool handlers ────────────────────────────────────────────────────────────

def open_file(filepath: str, line: Optional[int] = None) -> str:
    try:
        filepath = _resolve(filepath)
        if not os.path.exists(filepath):
            return f"❌ File not found: {filepath}"
        if line:
            cmd = ["code", "-g", f"{filepath}:{int(line)}"]
        else:
            cmd = ["code", filepath]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return f"✅ Opened in VS Code: {filepath}"
        if platform.system() == "Darwin":
            subprocess.run(["open", "-a", "Visual Studio Code", filepath], timeout=10)
            return f"✅ Opened in VS Code: {filepath}"
        return "⚠️ Could not open — is VS Code installed?"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def read_file(filepath: str) -> str:
    try:
        filepath = _resolve(filepath)
        size = os.path.getsize(filepath)
        if size > MAX_FILE_SIZE:
            return f"❌ File too large ({size // 1024}KB). Max {MAX_FILE_SIZE // 1024}KB."
        return Path(filepath).read_text(errors="replace")
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error reading file: {e}"


def create_file(filepath: str, content: str) -> str:
    try:
        filepath = _resolve(filepath)
        if len(content.encode()) > MAX_FILE_SIZE:
            return "❌ Content too large"
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"✅ Created: {filepath} ({len(content)} bytes)"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def edit_file(filepath: str, old_text: str, new_text: str) -> str:
    try:
        filepath = _resolve(filepath)
        p = Path(filepath)
        if not p.exists():
            return f"❌ File not found: {filepath}"
        content = p.read_text()
        if old_text not in content:
            return f"❌ Text not found in file"
        p.write_text(content.replace(old_text, new_text))
        return f"✅ Edited: {filepath}"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def delete_file(filepath: str) -> str:
    try:
        filepath = _resolve(filepath)
        Path(filepath).unlink()
        return f"✅ Deleted: {filepath}"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def list_files(directory: str = ".", path: str = None, dirpath: str = None) -> str:
    if dirpath and directory == ".":
        directory = dirpath
    elif path and directory == ".":
        directory = path
    try:
        directory = _resolve(directory)
        entries = sorted(os.listdir(directory))
        lines = []
        for e in entries:
            full = os.path.join(directory, e)
            prefix = "📁" if os.path.isdir(full) else "📄"
            lines.append(f"{prefix} {e}")
        return f"📂 {directory}\n" + "\n".join(lines) if lines else f"📂 {directory} (empty)"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def browse_directory(directory: str = ".", path: str = None) -> str:
    if path and directory == ".":
        directory = path
    try:
        directory = _resolve(directory)
        lines = [f"📂 {directory}"]
        for root, dirs, files in os.walk(directory):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            level = root.replace(directory, "").count(os.sep)
            if level > 3:
                continue
            indent = "  " * level
            lines.append(f"{indent}📁 {os.path.basename(root)}/")
            for f in files:
                lines.append(f"{indent}  📄 {f}")
        return "\n".join(lines)
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def run_command(command: str, cwd: Optional[str] = None) -> str:
    BLOCKED = [
        r'\brm\s+-rf\s+[/~]', r'\bmkfs\b', r'\bdd\s+if=',
        r':(){ :\|:& };:', r'\b>\/dev\/sd', r'\bsudo\s+rm\b',
    ]
    if any(re.search(p, command, re.IGNORECASE) for p in BLOCKED):
        return "❌ BLOCKED: Dangerous command pattern"
    try:
        if cwd:
            cwd = _resolve(cwd)
        else:
            cwd = _get_workspace()
        result = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT,
        )
        output = result.stdout + result.stderr
        return output.strip() or f"✅ Command completed (exit {result.returncode})"
    except subprocess.TimeoutExpired:
        return f"❌ Command timed out after {COMMAND_TIMEOUT}s"
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def git_status(repo_path: Optional[str] = None) -> str:
    cwd = _resolve(repo_path) if repo_path else _get_workspace()
    try:
        r = subprocess.run(["git", "status"], cwd=cwd, capture_output=True, text=True, timeout=10)
        return r.stdout + r.stderr
    except Exception as e:
        return f"❌ git error: {e}"


def git_command(command: str, repo_path: Optional[str] = None) -> str:
    cwd = _resolve(repo_path) if repo_path else _get_workspace()
    try:
        # Strip leading "git " if caller included it
        if command.strip().startswith("git "):
            command = command.strip()[4:]
        args = shlex.split(f"git {command}")
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr
    except Exception as e:
        return f"❌ git error: {e}"


def search_files(query: str = "", directory: str = ".", pattern: str = None, search_path: str = None, file_type: str = None) -> str:
    if pattern and not query:
        query = pattern
    if search_path and directory == ".":
        directory = search_path
    try:
        directory = _resolve(directory)
        matches = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if query.lower() in fname.lower():
                    matches.append(os.path.join(root, fname))
                    if len(matches) >= 50:
                        break
            if len(matches) >= 50:
                break
        if not matches:
            return f"No files matching '{query}'"
        return "\n".join(matches)
    except ValueError as e:
        return f"❌ {e}"
    except Exception as e:
        return f"❌ Error: {e}"


def get_workspace_info() -> str:
    ws = _get_workspace()
    return (
        f"Workspace: {ws}\n"
        f"OS: {platform.system()} {platform.release()}\n"
        f"Python: {platform.python_version()}\n"
        f"Host: {platform.node()}"
    )


def _clean_terminal_output(text: str) -> str:
    """Strip ANSI codes, control characters, and terminal noise from CLI output."""
    # ESC sequences: CSI, OSC, and standalone
    text = re.sub(r'\x1b(?:\[[0-9;?]*[a-zA-Z]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[\\=><MNOPQRSTUVWXYZ])', '', text)
    # script encodes EOT as literal "^D" — remove it
    text = text.replace('^D', '')
    # All control chars except newline (0x0a) and tab (0x09)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = text.replace('\r', '')
    # gh upgrade nag and copilot stats footer
    text = re.sub(r'\nA new release of gh.*', '', text, flags=re.DOTALL)
    text = re.sub(r'\nChanges\s+\+\d+.*', '', text, flags=re.DOTALL)
    return text.strip()


def copilot_agent(prompt: str, project_path: Optional[str] = None, model: str = "", allow_tools: str = "all") -> str:
    """Run GitHub Copilot agent CLI on the user's machine via script (fake TTY)."""
    cwd = _resolve(project_path) if project_path else _get_workspace()
    check = subprocess.run(["which", "gh"], capture_output=True, text=True, timeout=5)
    if check.returncode != 0:
        return "❌ GitHub CLI (gh) not installed. Run: brew install gh && gh auth login"
    try:
        # gh copilot requires a TTY — use `script` to fake one on macOS/Linux
        inner_cmd = f"gh copilot -- -p {shlex.quote(prompt)} --yolo --plain-diff"
        if model:
            inner_cmd += f" --model {shlex.quote(model)}"
        if platform.system() == "Darwin":
            cmd = ["script", "-q", "/dev/null", "bash", "-c", inner_cmd]
        else:
            cmd = ["script", "-q", "-c", inner_cmd, "/dev/null"]
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        output = _clean_terminal_output(output)
        return output or "✅ Copilot agent completed (no output)"
    except subprocess.TimeoutExpired:
        return "❌ Copilot agent timed out after 120s"
    except Exception as e:
        return f"❌ Copilot agent error: {e}"


def ask_agent(prompt: str, agent: str = "claude", project_path: Optional[str] = None, model: str = "", allow_tools: str = "all") -> str:
    """Run an AI agent CLI on the user's machine (claude, gh copilot, codex)."""
    cwd = _resolve(project_path) if project_path else _get_workspace()
    agent = (agent or "claude").lower().strip()

    try:
        if agent in ("claude", "claude-code"):
            check = subprocess.run(["which", "claude"], capture_output=True, text=True, timeout=5)
            if check.returncode != 0:
                return "❌ Claude Code CLI not installed. Run: npm install -g @anthropic-ai/claude-code"
            cmd = ["claude", "--print", prompt]
            if model:
                cmd += ["--model", model]
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
            return (result.stdout + result.stderr).strip() or "✅ Claude completed (no output)"

        elif agent in ("copilot", "gh-copilot"):
            check = subprocess.run(["which", "gh"], capture_output=True, text=True, timeout=5)
            if check.returncode != 0:
                return "❌ GitHub CLI (gh) not installed. Run: brew install gh && gh auth login"
            inner_cmd = f"gh copilot -- -p {shlex.quote(prompt)} --yolo --plain-diff"
            if model:
                inner_cmd += f" --model {shlex.quote(model)}"
            if platform.system() == "Darwin":
                cmd = ["script", "-q", "/dev/null", "bash", "-c", inner_cmd]
            else:
                cmd = ["script", "-q", "-c", inner_cmd, "/dev/null"]
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
            output = _clean_terminal_output(result.stdout + result.stderr)
            return output or "✅ Copilot completed (no output)"

        elif agent in ("codex", "openai-codex"):
            # codex runs via npx @openai/codex — no global install needed
            cmd = ["npx", "--yes", "@openai/codex", "exec",
                   "--dangerously-bypass-approvals-and-sandbox", prompt]
            result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
            output = _clean_terminal_output(result.stdout + result.stderr)
            # Strip codex session header and tokens footer, keep just the response
            output = re.sub(r'^.*?--------\nuser\n.*?\ncodex\n', '', output, flags=re.DOTALL).strip()
            output = re.sub(r'\ntokens used\n.*$', '', output, flags=re.DOTALL).strip()
            return output or "✅ Codex completed (no output)"

        else:
            return f"❌ Unknown agent '{agent}'. Supported: claude, copilot, codex"

    except subprocess.TimeoutExpired:
        return f"❌ Agent '{agent}' timed out"
    except Exception as e:
        return f"❌ Agent error: {e}"


def open_terminal(path: Optional[str] = None, cwd: Optional[str] = None) -> str:
    if cwd and not path:
        path = cwd
    target = _resolve(path) if path else _get_workspace()
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", "Terminal", target])
            return f"✅ Terminal opened at {target}"
        # On Linux/servers there's usually no GUI — return the path instead
        return f"ℹ No GUI terminal available. SSH to this machine and cd {target}"
    except Exception as e:
        return f"❌ Error: {e}"


# ─── Dispatch table ───────────────────────────────────────────────────────────

_HANDLERS = {
    "open_file": open_file,
    "read_file": read_file,
    "create_file": create_file,
    "edit_file": edit_file,
    "delete_file": delete_file,
    "list_files": list_files,
    "browse_directory": browse_directory,
    "run_command": run_command,
    "git_status": git_status,
    "git_command": git_command,
    "search_files": search_files,
    "get_workspace_info": get_workspace_info,
    "open_terminal": open_terminal,
    "copilot_agent": copilot_agent,
    "ask_agent": ask_agent,
}


def execute(tool_name: str, params: dict) -> dict:
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"success": False, "result": f"❌ Unknown tool: {tool_name}"}
    try:
        result = handler(**{k: v for k, v in params.items() if v is not None})
        return {"success": not str(result).startswith("❌"), "result": result}
    except TypeError as e:
        return {"success": False, "result": f"❌ Bad parameters: {e}"}
    except Exception as e:
        return {"success": False, "result": f"❌ Tool error: {e}"}
