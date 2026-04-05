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
    if os.path.isabs(path):
        resolved = os.path.realpath(path)
    else:
        resolved = os.path.realpath(os.path.join(workspace, path))
    if resolved.startswith(workspace + os.sep) or resolved == workspace:
        return resolved
    if resolved.startswith("/tmp/"):
        return resolved
    raise ValueError(f"Access denied: path '{path}' is outside the workspace")


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


def list_files(directory: str = ".") -> str:
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


def browse_directory(directory: str = ".") -> str:
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
        args = shlex.split(f"git {command}")
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=30)
        return r.stdout + r.stderr
    except Exception as e:
        return f"❌ git error: {e}"


def search_files(query: str, directory: str = ".") -> str:
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


def open_terminal(path: Optional[str] = None) -> str:
    target = _resolve(path) if path else _get_workspace()
    try:
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-a", "Terminal", target])
        elif platform.system() == "Linux":
            subprocess.Popen(["xterm", "-e", f"cd {shlex.quote(target)} && bash"])
        return f"✅ Terminal opened at {target}"
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
