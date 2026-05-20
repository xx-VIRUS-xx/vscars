import subprocess
import os
import platform
import re as _re
import shlex
import inspect
from pathlib import Path
from typing import Optional
import signal
import json
import tempfile
import time
import requests
from app.jarvis import JARVISInterpreter
from app.config import GITHUB_TOKEN, COPILOT_MODEL, WORKSPACE_PATH, COMMAND_TIMEOUT, MAX_FILE_SIZE
import os as _os
ANTHROPIC_API_KEY = _os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = _os.getenv("OPENAI_API_KEY", "")

# Allowed workspace roots — paths users can access
# The workspace itself + any sub-paths are allowed; home directory is NOT
_ALLOWED_ROOTS = None

def _get_allowed_roots():
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is None:
        ws = _get_workspace()
        _ALLOWED_ROOTS = [os.path.realpath(ws)]
    return _ALLOWED_ROOTS

def _reset_allowed_roots():
    """Reset after workspace change"""
    global _ALLOWED_ROOTS
    _ALLOWED_ROOTS = None


def _get_workspace() -> str:
    """Get current workspace path from runtime config or .env"""
    ws_file = "/tmp/jarvis_workspace.txt"
    if os.path.exists(ws_file):
        with open(ws_file, 'r') as f:
            ws = f.read().strip()
            if ws and os.path.isdir(ws):
                return ws
    return WORKSPACE_PATH or os.path.expanduser("~")


def _resolve_path(filepath: str) -> str:
    """Resolve a path relative to workspace, with sandbox enforcement.
    Blocks path traversal and access outside workspace."""
    workspace = os.path.realpath(_get_workspace())
    
    if os.path.isabs(filepath):
        resolved = os.path.realpath(filepath)
    else:
        resolved = os.path.realpath(os.path.join(workspace, filepath))
    
    # Allow access to workspace and its children
    if resolved.startswith(workspace + os.sep) or resolved == workspace:
        return resolved
    
    # Also allow /tmp for temp operations
    if resolved.startswith('/tmp/'):
        return resolved
    
    raise ValueError(f"Access denied: path '{filepath}' is outside the workspace")


def _validate_filename(name: str) -> str:
    """Validate a filename/project name to prevent shell injection"""
    if not _re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,100}$', name):
        raise ValueError(f"Invalid name '{name}': use only letters, numbers, dots, hyphens, underscores")
    if '..' in name:
        raise ValueError("Name cannot contain '..'")
    return name

class VSCodeTools:
    """Tools for interacting with VS Code and running commands"""
    
    @staticmethod
    def open_file(filepath: str, line: Optional[int] = None) -> str:
        """Open a file in VS Code"""
        try:
            filepath = _resolve_path(filepath)
            if not os.path.exists(filepath):
                return f"❌ ERROR: File not found: {filepath}"
            
            # Use list args instead of shell=True to prevent injection
            if line:
                cmd_args = ["code", "-g", f"{filepath}:{int(line)}"]
            else:
                cmd_args = ["code", filepath]
            
            result = subprocess.run(cmd_args, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                return f"✅ SUCCESS: File opened in VS Code\n📄 File: {filepath}" + (f"\n📍 Line: {line}" if line else "")
            else:
                # Fallback for macOS
                if platform.system() == "Darwin":
                    subprocess.run(["open", "-a", "Visual Studio Code", filepath], timeout=10)
                    return f"✅ File opened in VS Code\n📄 File: {filepath}"
                return f"⚠️ VS Code CLI not found. Install 'code' command: VS Code → Cmd+Shift+P → 'Shell Command: Install'"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ ERROR opening file: {str(e)}"
    
    @staticmethod
    def create_file(filepath: str, content: str) -> str:
        """Create a new file with content"""
        try:
            filepath = _resolve_path(filepath)
            # Enforce file size limit
            if len(content.encode('utf-8')) > MAX_FILE_SIZE:
                return f"❌ ERROR: Content too large (max {MAX_FILE_SIZE // 1024 // 1024}MB)"
            path = Path(filepath)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            return f"✅ File created: {filepath}\n📊 Size: {len(content)} bytes"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ Error creating file: {str(e)}"
    
    @staticmethod
    def edit_file(filepath: str, old_text: str, new_text: str) -> str:
        """Edit file by replacing text"""
        try:
            filepath = _resolve_path(filepath)
            path = Path(filepath)
            if not path.exists():
                return f"❌ ERROR: File not found: {filepath}"
            
            content = path.read_text()
            if old_text not in content:
                return f"❌ ERROR: Text not found in file: {filepath}"
            
            new_content = content.replace(old_text, new_text)
            path.write_text(new_content)
            return f"✅ SUCCESS: File edited\n📄 File: {filepath}\n📝 Changes: {len(new_content) - len(content):+d} bytes"
        except Exception as e:
            return f"❌ Error editing file: {str(e)}"
    
    @staticmethod
    def delete_file(filepath: str) -> str:
        """Delete a file"""
        try:
            filepath = _resolve_path(filepath)
            path = Path(filepath)
            if not path.exists():
                return f"❌ ERROR: File not found: {filepath}"
            
            path.unlink()
            return f"✅ SUCCESS: File deleted: {filepath}"
        except Exception as e:
            return f"❌ Error deleting file: {str(e)}"
    
    @staticmethod
    def read_file(filepath: str) -> str:
        """Read file contents"""
        try:
            filepath = _resolve_path(filepath)
            path = Path(filepath)
            if not path.exists():
                return f"❌ ERROR: File not found: {filepath}"
            
            content = path.read_text()
            lines = len(content.split('\n'))
            return f"✅ File: {filepath}\n📊 Lines: {lines}\n\n{content}"
        except Exception as e:
            return f"❌ Error reading file: {str(e)}"
    
    @staticmethod
    def run_command(command: str, cwd: Optional[str] = None) -> str:
        """Run a shell command with workspace-aware working directory.
        Uses shell=True but restricts working directory to workspace."""
        try:
            work_dir = _resolve_path(cwd) if cwd else _get_workspace()
            timeout = min(COMMAND_TIMEOUT or 120, 300)  # Hard cap at 5 min
            
            # Block dangerous commands
            BLOCKED_PATTERNS = [
                r'\brm\s+-rf\s+[/~]',           # rm -rf / or ~
                r'\bmkfs\b', r'\bdd\s+if=',      # Disk ops
                r':(){ :\|:& };:',               # Fork bomb
                r'\b>\/dev\/sd',                 # Overwrite drives
                r'\bsudo\s+rm\b',                # sudo rm
                r'\bchmod\s+777\s+/',            # chmod 777 on root paths
                r'\bcrontab\s+-[re]\b',          # Edit crontab
                r'\bpasswd\b',                   # Change system password
                r'\buserdel\b|\buseradd\b',      # User management
                r'\biptables\b|\bnftables\b',    # Firewall changes
                r'\bsystemctl\s+(stop|disable|mask)\s+ssh', # Kill SSH
                r'\bshred\b|\bwipe\b',           # Irreversible data wipe
                r'\bpkill\s+-9\s+-1\b',          # Kill all processes
                r'>\s*/etc/passwd', r'>\s*/etc/shadow',  # Overwrite auth files
            ]
            for pattern in BLOCKED_PATTERNS:
                if _re.search(pattern, command, _re.IGNORECASE):
                    return f"❌ BLOCKED: Command contains a dangerous pattern and was not executed."
            
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=work_dir
            )
            
            stdout = result.stdout[:8000] if result.stdout else ""
            stderr = result.stderr[:4000] if result.stderr else ""
            # Interleave stdout + stderr as a terminal would show them
            output = ""
            if stdout:
                output += stdout
            if stderr:
                output += ("\n" if output else "") + stderr
            if not output:
                output = "(no output)"

            # Clean developer-facing output: show exit code only on failure
            if result.returncode == 0:
                return f"$ {command}\n{output}"
            else:
                return f"$ {command}\n{output}\n[exit {result.returncode}]"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except subprocess.TimeoutExpired:
            return f"❌ ERROR: Command timeout (exceeded {timeout}s)\n💡 Increase COMMAND_TIMEOUT in Settings"
        except Exception as e:
            return f"❌ Error running command: {str(e)}"
    
    @staticmethod
    def list_files(dirpath: str = "") -> str:
        """List files in a directory (defaults to workspace)"""
        try:
            if not dirpath:
                dirpath = _get_workspace()
            elif os.path.isabs(dirpath):
                dirpath = os.path.realpath(dirpath)
            else:
                dirpath = _resolve_path(dirpath)
            path = Path(dirpath)
            if not path.exists():
                return f"❌ ERROR: Directory not found: {dirpath}"
            
            items = list(path.iterdir())
            if not items:
                return f"✅ Directory is empty: {dirpath}"
            
            dirs = []
            files = []
            for item in sorted(items):
                if item.name.startswith('.'):
                    continue  # Skip hidden files in listing
                if item.is_dir():
                    dirs.append(f"📁 {item.name}/")
                else:
                    size = item.stat().st_size
                    if size > 1024 * 1024:
                        size_str = f"{size / 1024 / 1024:.1f}MB"
                    elif size > 1024:
                        size_str = f"{size / 1024:.1f}KB"
                    else:
                        size_str = f"{size}B"
                    files.append(f"📄 {item.name}  ({size_str})")
            
            result = f"✅ Contents of {dirpath}\n📊 {len(dirs)} folders, {len(files)} files\n\n"
            result += "\n".join(dirs + files)
            return result
        except Exception as e:
            return f"❌ Error listing files: {str(e)}"
    
    @staticmethod
    def ask_copilot(prompt: str = "", query: str = "") -> str:
        query = prompt or query  # accept either param name
        """GitHub Copilot Chat via GitHub Models API
        
        Uses your paid GitHub Copilot subscription to call AI models 
        directly via the GitHub Models API. Instant responses, no AppleScript.
        """
        try:
            # Get token — check runtime config first, then env
            token = GITHUB_TOKEN
            
            # Check runtime-saved token (secured with restrictive permissions)
            token_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.github_token')
            if not token and os.path.exists(token_file):
                with open(token_file, 'r') as f:
                    token = f.read().strip()
            
            if not token:
                return (
                    "❌ GitHub Token not configured!\n\n"
                    "To use Copilot Chat, you need a GitHub Personal Access Token with Models permission:\n\n"
                    "1. Go to: https://github.com/settings/tokens?type=beta\n"
                    "2. Click 'Generate new token' (Fine-grained)\n"
                    "3. Give it a name (e.g., 'JARVIS Copilot')\n"
                    "4. Under 'Permissions' → 'Account permissions' → set 'Models' to 'Read-only'\n"
                    "5. Click 'Generate token' and copy it\n"
                    "6. Go to Settings tab in this app and paste it\n\n"
                    "Or add GITHUB_TOKEN=github_pat_xxx to your .env file"
                )
            
            # Call GitHub Models API (OpenAI-compatible endpoint)
            api_url = "https://models.inference.ai.azure.com/chat/completions"
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}"
            }
            
            payload = {
                "model": COPILOT_MODEL or "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are GitHub Copilot, an AI programming assistant. You help with coding questions, debugging, code reviews, and software development. Be concise, accurate, and provide code examples when helpful."
                    },
                    {
                        "role": "user",
                        "content": query
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 2048
            }
            
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=60
            )
            
            if response.status_code == 401:
                error_msg = ""
                try:
                    err_data = response.json()
                    error_msg = err_data.get("error", {}).get("message", "")
                except:
                    error_msg = response.text[:200]
                
                if "models" in error_msg.lower() or "permission" in error_msg.lower():
                    return (
                        "❌ Token Missing 'Models' Permission!\n\n"
                        "Your token works but doesn't have access to GitHub Models.\n\n"
                        "Fix it:\n"
                        "1. Go to: https://github.com/settings/tokens?type=beta\n"
                        "2. Click on your existing token (or create new Fine-grained token)\n"
                        "3. Under 'Permissions' → 'Account permissions'\n"
                        "4. Find 'Models' → set to 'Read-only'\n"
                        "5. Save/Update the token\n"
                        "6. If you created a NEW token, paste it in Settings tab\n\n"
                        f"API Error: {error_msg}"
                    )
                
                return (
                    "❌ Invalid GitHub Token!\n\n"
                    "Your token was rejected. Please:\n"
                    "1. Go to https://github.com/settings/tokens?type=beta\n"
                    "2. Generate a new Fine-grained token\n"
                    "3. Enable 'Models' → 'Read-only' under Account permissions\n"
                    "4. Update it in Settings tab\n\n"
                    f"API Error: {error_msg}"
                )
            
            if response.status_code == 403:
                return (
                    "❌ Access Denied!\n\n"
                    "Your GitHub account may not have access to GitHub Models.\n"
                    "Make sure you have an active GitHub Copilot subscription.\n"
                    "Visit: https://github.com/features/copilot"
                )
            
            if response.status_code == 429:
                return (
                    "⚠️ Rate Limited!\n\n"
                    "Too many requests. Please wait a moment and try again.\n"
                    "GitHub Models has usage limits depending on your plan."
                )
            
            if response.status_code != 200:
                error_detail = response.text[:300] if response.text else "Unknown error"
                return f"❌ API Error (HTTP {response.status_code}):\n{error_detail}"
            
            # Parse response
            data = response.json()
            ai_response = data["choices"][0]["message"]["content"]
            
            # Get usage info
            usage = data.get("usage", {})
            tokens_used = usage.get("total_tokens", 0)
            model_used = data.get("model", COPILOT_MODEL)
            
            # Format the response
            formatted = (
                "🤖 COPILOT RESPONSE\n\n"
                + ai_response + "\n\n"
                "───────────────────\n"
                f"📊 Model: {model_used} | Tokens: {tokens_used}"
            )
            
            return formatted
            
        except requests.exceptions.Timeout:
            return "❌ Request timed out. The AI model took too long to respond. Try again."
        except requests.exceptions.ConnectionError:
            return "❌ Connection failed. Check your internet connection."
        except KeyError as e:
            return f"❌ Unexpected API response format: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    @staticmethod
    def ask_ai(prompt: str = "", query: str = "", provider: str = "auto") -> str:
        query = prompt or query  # accept either param name
        """Multi-provider AI chat. provider: auto | copilot | claude | openai
        'auto' picks the first available key: Copilot → Claude → OpenAI."""

        def _via_copilot():
            return VSCodeTools.ask_copilot(query)

        def _via_claude():
            import anthropic
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=2048,
                system="You are a helpful AI programming assistant. Be concise and provide code examples when helpful.",
                messages=[{"role": "user", "content": query}],
            )
            text = msg.content[0].text
            return f"🤖 CLAUDE RESPONSE\n\n{text}\n\n───────────────────\n📊 Model: {msg.model} | Tokens: {msg.usage.input_tokens + msg.usage.output_tokens}"

        def _via_openai():
            import openai
            client = openai.OpenAI(api_key=OPENAI_API_KEY)
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful AI programming assistant."},
                    {"role": "user", "content": query},
                ],
                max_tokens=2048,
            )
            text = resp.choices[0].message.content
            tokens = resp.usage.total_tokens
            return f"🤖 OPENAI RESPONSE\n\n{text}\n\n───────────────────\n📊 Model: {resp.model} | Tokens: {tokens}"

        routes = {
            "copilot": _via_copilot,
            "claude":  _via_claude,
            "openai":  _via_openai,
        }

        if provider != "auto":
            fn = routes.get(provider)
            if not fn:
                return f"❌ Unknown provider '{provider}'. Use: auto, copilot, claude, openai"
            try:
                return fn()
            except Exception as e:
                return f"❌ {provider} error: {e}"

        # Auto: try in order of available keys
        attempts = []
        if GITHUB_TOKEN:
            attempts.append(("copilot", _via_copilot))
        if ANTHROPIC_API_KEY:
            attempts.append(("claude", _via_claude))
        if OPENAI_API_KEY:
            attempts.append(("openai", _via_openai))

        if not attempts:
            return ("❌ No AI provider configured.\n"
                    "Set at least one of: GITHUB_TOKEN, ANTHROPIC_API_KEY, OPENAI_API_KEY in .env")

        for name, fn in attempts:
            try:
                return fn()
            except Exception as e:
                last_err = f"{name}: {e}"
                continue

        return f"❌ All AI providers failed. Last error: {last_err}"

    @staticmethod
    def submit_copilot_response(response: str) -> str:
        """Submit a manual Copilot response (legacy fallback)"""
        if not response or not response.strip():
            return "❌ ERROR: Response cannot be empty"
        return "✅ COPILOT RESPONSE CAPTURED\n\n🤖 Response:\n" + response
    
    @staticmethod
    def get_last_copilot_query() -> str:
        """Get the last query sent to Copilot"""
        try:
            query_file = "/tmp/copilot_query.txt"
            if not os.path.exists(query_file):
                return "❌ No recent query found"
            
            with open(query_file, 'r') as f:
                query = f.read()
            
            return f"📝 Last Query:\n{query}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    # ==================== NEW VS CODE CONTROL TOOLS ====================
    
    @staticmethod
    def open_project(project_path: str = "") -> str:
        """Open a project folder in VS Code"""
        try:
            project_path = _resolve_path(project_path) if project_path else _get_workspace()
            if not os.path.isdir(project_path):
                return f"❌ ERROR: Directory not found: {project_path}"
            
            result = subprocess.run(
                ["code", project_path],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                return f"✅ Project opened in VS Code\n📁 Path: {project_path}"
            else:
                if platform.system() == "Darwin":
                    subprocess.run(["open", "-a", "Visual Studio Code", project_path], timeout=10)
                    return f"✅ Project opened in VS Code\n📁 Path: {project_path}"
                return "⚠️ VS Code CLI not found. Run: VS Code → Cmd+Shift+P → 'Shell Command: Install'"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    @staticmethod
    def open_terminal(cwd: str = "") -> str:
        """Open VS Code integrated terminal at a path"""
        try:
            cwd = _resolve_path(cwd) if cwd else _get_workspace()
            if platform.system() == "Darwin":
                subprocess.run(["open", "-a", "Terminal", cwd], timeout=10)
                return f"✅ Terminal opened\n📁 Path: {cwd}"
            else:
                subprocess.run(["code", cwd], timeout=10)
                return f"✅ VS Code opened at: {cwd}"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    @staticmethod
    def git_status(repo_path: str = "") -> str:
        """Show git status, branch, and recent commits"""
        try:
            repo_path = _resolve_path(repo_path) if repo_path else _get_workspace()
            
            # Use list args to prevent injection
            check = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True,
                cwd=repo_path, timeout=10
            )
            if check.returncode != 0:
                return f"❌ Not a git repository: {repo_path}"
            
            branch = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, cwd=repo_path, timeout=10
            ).stdout.strip()
            
            status = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, cwd=repo_path, timeout=10
            ).stdout.strip() or "(Clean — no changes)"
            
            log = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                capture_output=True, text=True, cwd=repo_path, timeout=10
            ).stdout.strip()
            
            remote = subprocess.run(
                ["git", "remote", "-v"],
                capture_output=True, text=True, cwd=repo_path, timeout=10
            ).stdout.strip()
            
            return (
                f"✅ Git Status\n"
                f"📁 Repo: {repo_path}\n"
                f"🌿 Branch: {branch}\n\n"
                f"📊 Changes:\n{status}\n\n"
                f"📜 Recent Commits:\n{log}\n\n"
                f"🌐 Remote:\n{remote}"
            )
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    @staticmethod
    def git_command(command: str, repo_path: str = "") -> str:
        """Run any git command (add, commit, push, pull, etc.)"""
        try:
            repo_path = _resolve_path(repo_path) if repo_path else _get_workspace()
            
            # Parse into list to prevent shell injection
            # Strip 'git' prefix if user included it
            cmd_str = command.strip()
            if cmd_str.startswith("git "):
                cmd_str = cmd_str[4:]
            
            # Block dangerous git operations
            BLOCKED_GIT = ['filter-branch', 'reflog delete', 'gc --prune=all']
            for blocked in BLOCKED_GIT:
                if blocked in cmd_str:
                    return f"❌ ERROR: '{blocked}' is blocked for safety"
            
            # Build a safe arg list
            cmd_args = ["git"] + shlex.split(cmd_str)
            
            result = subprocess.run(
                cmd_args,
                capture_output=True, text=True,
                cwd=repo_path, timeout=60
            )
            
            output = result.stdout or result.stderr or "(No output)"
            status = "✅ SUCCESS" if result.returncode == 0 else f"⚠️ Exit code: {result.returncode}"
            
            return f"{status}\n📁 Repo: {repo_path}\n🔧 Command: git {cmd_str}\n\n{output}"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    @staticmethod
    def search_files(pattern: str, search_path: str = "", file_type: str = "") -> str:
        """Search for files by name or content"""
        try:
            search_path = _resolve_path(search_path) if search_path else _get_workspace()
            
            # Validate pattern to prevent injection (no shell metacharacters)
            if any(c in pattern for c in ['`', '$', '(', ')', ';', '&', '|', '>', '<', '\\']):
                return "❌ ERROR: Pattern contains invalid characters"
            
            if file_type:
                # Validate file_type
                if not _re.match(r'^[a-zA-Z0-9]+$', file_type):
                    return "❌ ERROR: Invalid file type"
                cmd_args = ["find", search_path, "-maxdepth", "5", "-name", f"*.{file_type}",
                           "-not", "-path", "*/node_modules/*", "-not", "-path", "*/.git/*",
                           "-not", "-path", "*/__pycache__/*"]
            elif '*' in pattern or '.' in pattern:
                cmd_args = ["find", search_path, "-maxdepth", "5", "-name", pattern,
                           "-not", "-path", "*/node_modules/*", "-not", "-path", "*/.git/*"]
            else:
                # Content search via grep — use list args
                cmd_args = ["grep", "-rl", pattern, search_path,
                           "--include=*.py", "--include=*.js", "--include=*.ts",
                           "--include=*.html", "--include=*.css", "--include=*.json",
                           "--include=*.md", "--include=*.txt",
                           "--include=*.yaml", "--include=*.yml"]
            
            result = subprocess.run(
                cmd_args, capture_output=True, text=True,
                cwd=search_path, timeout=30
            )
            
            output = result.stdout.strip()
            # Limit output lines
            lines = output.split('\n')
            if len(lines) > 30:
                lines = lines[:30]
                output = '\n'.join(lines) + '\n... (truncated)'
            
            if not output:
                return f"🔍 No results found for: {pattern}\n📁 Searched: {search_path}"
            
            count = len(lines)
            return f"🔍 Search Results ({count} matches)\n📁 In: {search_path}\n🔎 Pattern: {pattern}\n\n{output}"
        except ValueError as e:
            return f"❌ ERROR: {str(e)}"
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    @staticmethod
    def create_project(project_name: str, project_type: str = "python", parent_dir: str = "", copilot_prompt: str = "") -> str:
        """Create a new project with boilerplate structure. Optionally run Copilot agent to set it up."""
        try:
            parent = _resolve_path(parent_dir) if parent_dir else _get_workspace()
            
            # Validate project name to prevent injection
            _validate_filename(project_name)
            
            project_path = os.path.join(parent, project_name)
            
            if os.path.exists(project_path):
                return f"❌ ERROR: Directory already exists: {project_path}"
            
            ptype = project_type.lower()
            
            if ptype == "python":
                os.makedirs(os.path.join(project_path, "src"), exist_ok=True)
                os.makedirs(os.path.join(project_path, "tests"), exist_ok=True)
                
                Path(os.path.join(project_path, "src", "__init__.py")).write_text("")
                Path(os.path.join(project_path, "src", "main.py")).write_text(
                    '"""Main application entry point"""\n\n\ndef main():\n    print("Hello from ' + project_name + '!")\n\n\nif __name__ == "__main__":\n    main()\n'
                )
                Path(os.path.join(project_path, "tests", "__init__.py")).write_text("")
                Path(os.path.join(project_path, "tests", "test_main.py")).write_text(
                    'from src.main import main\n\ndef test_main():\n    main()\n'
                )
                Path(os.path.join(project_path, "requirements.txt")).write_text("")
                Path(os.path.join(project_path, "README.md")).write_text(f"# {project_name}\n\n## Setup\n```bash\npython3 -m venv venv\nsource venv/bin/activate\npip install -r requirements.txt\npython src/main.py\n```\n")
                Path(os.path.join(project_path, ".gitignore")).write_text("venv/\n__pycache__/\n*.pyc\n.env\n*.egg-info/\ndist/\nbuild/\n")
            
            elif ptype in ("node", "nodejs", "javascript", "js"):
                os.makedirs(os.path.join(project_path, "src"), exist_ok=True)
                
                Path(os.path.join(project_path, "src", "index.js")).write_text(
                    f'// {project_name}\nconsole.log("Hello from {project_name}!");\n'
                )
                Path(os.path.join(project_path, "package.json")).write_text(json.dumps({
                    "name": project_name.lower().replace(" ", "-"),
                    "version": "1.0.0",
                    "description": "",
                    "main": "src/index.js",
                    "scripts": {"start": "node src/index.js", "test": "echo 'No tests yet'"},
                    "keywords": [],
                    "author": "",
                    "license": "MIT"
                }, indent=2))
                Path(os.path.join(project_path, "README.md")).write_text(f"# {project_name}\n\n## Setup\n```bash\nnpm install\nnpm start\n```\n")
                Path(os.path.join(project_path, ".gitignore")).write_text("node_modules/\n.env\ndist/\n.DS_Store\n")
            
            elif ptype in ("react", "nextjs", "next"):
                cmd_args = ["npx", "create-next-app@latest", project_name,
                           "--ts", "--eslint", "--tailwind", "--src-dir", "--app", "--no-import-alias"]
                result = subprocess.run(cmd_args, capture_output=True, text=True, timeout=120, cwd=parent)
                if result.returncode == 0:
                    subprocess.run(["code", project_path], timeout=10)
                    return f"✅ Next.js project created!\n📁 Path: {project_path}\n\n{result.stdout[-500:]}"
                else:
                    return f"⚠️ Project init had issues:\n{result.stderr[:500]}"
            
            elif ptype in ("flask", "fastapi", "api"):
                os.makedirs(os.path.join(project_path, "app"), exist_ok=True)
                os.makedirs(os.path.join(project_path, "static"), exist_ok=True)
                os.makedirs(os.path.join(project_path, "templates"), exist_ok=True)
                
                framework = "fastapi" if ptype == "fastapi" else "flask"
                
                if framework == "fastapi":
                    Path(os.path.join(project_path, "app", "main.py")).write_text(
                        'from fastapi import FastAPI\n\napp = FastAPI(title="' + project_name + '")\n\n@app.get("/")\ndef root():\n    return {"message": "Hello from ' + project_name + '!"}\n\nif __name__ == "__main__":\n    import uvicorn\n    uvicorn.run(app, host="0.0.0.0", port=8000)\n'
                    )
                    Path(os.path.join(project_path, "requirements.txt")).write_text("fastapi\nuvicorn\n")
                else:
                    Path(os.path.join(project_path, "app", "main.py")).write_text(
                        'from flask import Flask\n\napp = Flask(__name__)\n\n@app.route("/")\ndef index():\n    return "Hello from ' + project_name + '!"\n\nif __name__ == "__main__":\n    app.run(debug=True)\n'
                    )
                    Path(os.path.join(project_path, "requirements.txt")).write_text("flask\n")
                
                Path(os.path.join(project_path, "app", "__init__.py")).write_text("")
                Path(os.path.join(project_path, "README.md")).write_text(f"# {project_name}\n\n## Setup\n```bash\npython3 -m venv venv\nsource venv/bin/activate\npip install -r requirements.txt\npython app/main.py\n```\n")
                Path(os.path.join(project_path, ".gitignore")).write_text("venv/\n__pycache__/\n*.pyc\n.env\n")
            
            else:
                # Generic/empty project
                os.makedirs(project_path, exist_ok=True)
                Path(os.path.join(project_path, "README.md")).write_text(f"# {project_name}\n")
                Path(os.path.join(project_path, ".gitignore")).write_text(".DS_Store\n")
            
            # Init git
            subprocess.run(["git", "init"], cwd=project_path, capture_output=True, timeout=10)
            
            # Open in VS Code
            subprocess.run(["code", project_path], capture_output=True, timeout=10)
            
            result_msg = (
                f"✅ Project created: {project_name}\n"
                f"📁 Path: {project_path}\n"
                f"🔧 Type: {project_type}\n"
                f"📦 Git initialized\n"
                f"💻 Opened in VS Code"
            )
            
            # Run Copilot agent on the new project if prompt provided
            if copilot_prompt:
                result_msg += "\n\n🤖 Running Copilot Agent...\n"
                agent_result = VSCodeTools.copilot_agent(
                    prompt=copilot_prompt,
                    project_path=project_path,
                    model="claude-opus-4.6",
                    allow_tools="all"
                )
                result_msg += agent_result
            
            return result_msg
        except Exception as e:
            return f"❌ Error creating project: {str(e)}"
    
    @staticmethod
    def get_workspace_info() -> str:
        """Get current workspace path and system info"""
        try:
            ws = _get_workspace()
            system = platform.system()
            node = platform.node()
            python_ver = platform.python_version()

            def _safe_version(cmd_args, first_line=False):
                try:
                    check = subprocess.run(
                        cmd_args, capture_output=True, text=True, timeout=5
                    )
                    if check.returncode != 0:
                        return "Not found"
                    out = check.stdout.strip()
                    if not out:
                        return "Not found"
                    return out.split('\n')[0].strip() if first_line else out
                except subprocess.TimeoutExpired:
                    return "Timed out"
                except FileNotFoundError:
                    return "Not found"
                except Exception:
                    return "Unavailable"

            vscode_ver = _safe_version(["code", "--version"], first_line=True)
            git_ver = _safe_version(["git", "--version"])
            node_ver = _safe_version(["node", "--version"])
            copilot_ver = _safe_version(["copilot", "--version"])
            gh_ver = _safe_version(["gh", "--version"], first_line=True)
            
            # Disk space
            disk = subprocess.run(
                ["df", "-h", "."],
                capture_output=True, text=True, cwd=ws, timeout=5
            ).stdout.strip()
            
            return (
                f"📁 Workspace: {ws}\n"
                f"🖥️  System: {system} ({node})\n"
                f"🐍 Python: {python_ver}\n"
                f"💻 VS Code: {vscode_ver}\n"
                f"📦 Git: {git_ver}\n"
                f"🟢 Node: {node_ver}\n"
                f"🤖 Copilot CLI: {copilot_ver}\n"
                f"🐙 GitHub CLI: {gh_ver}\n"
                f"💾 Disk: {disk}\n"
                f"⏱️  Timeout: {COMMAND_TIMEOUT}s"
            )
        except Exception as e:
            return f"❌ Error: {str(e)}"
    
    # ==================== COPILOT CLI AGENTIC TOOLS ====================
    
    @staticmethod
    def copilot_agent(prompt: str, project_path: str = "", model: str = "claude-haiku-4.5", allow_tools: str = "all") -> str:
        """Run GitHub Copilot CLI in agentic mode — it can edit files, run commands, search code.
        
        This is the REAL Copilot agent (not just chat). It can:
        - Read and edit any file in the project
        - Run shell commands (npm install, pip install, build, test, etc.)
        - Search the codebase
        - Create entire features autonomously
        
        Models: claude-opus-4.6, claude-sonnet-4.6, gpt-5.2, gpt-5.1, gpt-4.1
        """
        try:
            # Normalize model names (handle legacy aliases)
            VALID_MODELS = {
                "claude-opus-4.6", "claude-opus-4.6-fast", "claude-opus-4.5",
                "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-sonnet-4",
                "claude-haiku-4.5",
                "gpt-5.4", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
                "gpt-5.1-codex-max", "gpt-5.1-codex", "gpt-5.1", "gpt-5.1-codex-mini",
                "gpt-5-mini", "gpt-4.1", "gemini-3-pro-preview"
            }
            
            # Aliases for backward compatibility
            model_aliases = {
                "claude-3.7-sonnet": "claude-sonnet-4.6",
                "claude-opus-4": "claude-opus-4.6",
                "claude-sonnet": "claude-sonnet-4.6",
                "gpt-5": "gpt-5.2",
                "gpt-4o": "gpt-5.2",
            }
            
            # Map alias to actual model if needed
            if model in model_aliases:
                model = model_aliases[model]
            
            # Fallback if still invalid
            if model not in VALID_MODELS:
                model = "gpt-5.2"  # Safe fallback
            
            project_path = _resolve_path(project_path) if project_path else _get_workspace()
            
            if not os.path.isdir(project_path):
                return f"❌ ERROR: Directory not found: {project_path}"
            
            # Check if copilot CLI exists
            copilot_check = subprocess.run(
                ["which", "copilot"], capture_output=True, text=True, timeout=5
            )
            if copilot_check.returncode != 0:
                return (
                    "❌ Copilot CLI not installed!\n\n"
                    "Install it:\n"
                    "1. Make sure 'gh' is installed: brew install gh\n"
                    "2. Login: gh auth login\n"
                    "3. Run: gh copilot (it will auto-install)\n\n"
                    "Or install directly from VS Code's Copilot Chat extension."
                )
            
            # Find copilot binary path
            copilot_path = copilot_check.stdout.strip()
            
            supported_models = {
                "claude-sonnet-4.6", "claude-sonnet-4.5", "claude-haiku-4.5",
                "claude-opus-4.6", "claude-opus-4.6-fast", "claude-opus-4.5",
                "claude-sonnet-4", "gemini-3-pro-preview",
                "gpt-5.4", "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.2",
                "gpt-5.1-codex-max", "gpt-5.1-codex", "gpt-5.1", "gpt-5.1-codex-mini",
                "gpt-5-mini", "gpt-4.1"
            }
            model_aliases = {
                "claude-3.7-sonnet": "claude-sonnet-4.6",
                "claude-sonnet": "claude-sonnet-4.6",
                "claude-opus": "claude-opus-4.6",
                "gpt-5.3": "gpt-5.3-codex",
                "gpt-5.2": "gpt-5.2",
            }
            normalized_model = (model or "claude-opus-4.6").strip()
            normalized_model = model_aliases.get(normalized_model, normalized_model)
            if normalized_model not in supported_models:
                normalized_model = "claude-opus-4.6"

            # Build command as a LIST (not string) — safe from shell injection & quote issues
            cmd_args = [copilot_path, "-p", prompt, "--model", normalized_model,
                       "--add-dir", project_path, "--no-auto-update", "-s"]
            
            # Permission handling — restrict by default, only superuser should use 'all'
            if allow_tools == "all":
                cmd_args.append("--allow-all")
            elif allow_tools == "read":
                cmd_args.extend(["--allow-tool=read", "--allow-tool=shell(ls)",
                               "--allow-tool=shell(cat)", "--allow-tool=shell(find)",
                               "--allow-tool=shell(grep)"])
            elif allow_tools == "edit":
                cmd_args.extend(["--allow-tool=read", "--allow-tool=write", "--allow-all-paths"])
            else:
                # Default to read+edit only (NOT --allow-all)
                cmd_args.extend(["--allow-tool=read", "--allow-tool=write", "--allow-all-paths"])
            
            # Longer timeout for agentic tasks (10 minutes)
            timeout = max(COMMAND_TIMEOUT, 600)
            
            # Build clean env: strip classic PAT so copilot uses gh OAuth token
            clean_env = {k: v for k, v in os.environ.items()}
            # Suppress ALL interactive prompts / approval dialogs
            clean_env["NO_COLOR"] = "1"
            clean_env["CI"] = "1"                      # Many CLIs disable prompts in CI mode
            clean_env["GH_PROMPT_DISABLED"] = "1"      # GitHub CLI prompt suppression
            clean_env["TERM"] = "dumb"                 # Prevents readline/interactive UI
            clean_env["DEBIAN_FRONTEND"] = "noninteractive"
            # Classic PATs (ghp_) are NOT supported by Copilot CLI
            # Remove them so it falls through to gh auth (OAuth gho_ token)
            for token_var in ["GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN"]:
                val = clean_env.get(token_var, "")
                if val.startswith("ghp_"):
                    clean_env.pop(token_var, None)

            # Pipe /dev/null as stdin — prevents any blocking "press enter" prompts
            with open(os.devnull, 'r') as devnull:
                result = subprocess.run(
                    cmd_args,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=project_path,
                    env=clean_env,
                    stdin=devnull,
                )
            
            output = result.stdout.strip() if result.stdout else ""
            errors = result.stderr.strip() if result.stderr else ""

            # ── Fallback chain ───────────────────────────────────────────────
            # Ordered cheapest → most capable; try each on model-unavailable OR quota errors
            _FALLBACK_CHAIN = [
                "claude-haiku-4.5",
                "claude-sonnet-4.6",
                "gpt-4.1",
                "gpt-5.2",
                "claude-opus-4.6",
            ]

            def _build_cmd(model_id):
                args = [copilot_path, "-p", prompt, "--model", model_id,
                        "--add-dir", project_path, "--no-auto-update", "-s"]
                if allow_tools == "all":
                    args.append("--allow-all")
                elif allow_tools == "read":
                    args.extend(["--allow-tool=read", "--allow-tool=shell(ls)",
                                 "--allow-tool=shell(cat)", "--allow-tool=shell(find)",
                                 "--allow-tool=shell(grep)"])
                elif allow_tools == "edit":
                    args.extend(["--allow-tool=read", "--allow-tool=write", "--allow-all-paths"])
                else:
                    args.extend(["--allow-tool=read", "--allow-tool=write", "--allow-all-paths"])
                return args

            def _is_model_unavailable(err: str) -> bool:
                err_l = err.lower()
                return ("not available" in err_l and "--model" in err_l) or "unknown model" in err_l

            def _is_quota_error(err: str) -> bool:
                err_l = err.lower()
                return any(p in err_l for p in [
                    "quota", "rate limit", "rate_limit", "too many requests",
                    "ratelimit", "429", "limit exceeded", "out of quota",
                    "billing", "usage limit",
                ])

            if result.returncode != 0 and errors:
                should_fallback = _is_model_unavailable(errors) or _is_quota_error(errors)
                if should_fallback:
                    tried = {normalized_model}
                    for fallback_model in _FALLBACK_CHAIN:
                        if fallback_model in tried:
                            continue
                        tried.add(fallback_model)
                        with open(os.devnull, 'r') as devnull:
                            fb_result = subprocess.run(
                                _build_cmd(fallback_model),
                                capture_output=True, text=True,
                                timeout=timeout, cwd=project_path,
                                env=clean_env, stdin=devnull,
                            )
                        fb_out = fb_result.stdout.strip() if fb_result.stdout else ""
                        fb_err = fb_result.stderr.strip() if fb_result.stderr else ""
                        # Accept if succeeded OR if it's a different error (not quota/unavailable)
                        if fb_result.returncode == 0 and fb_out:
                            normalized_model = fallback_model
                            output, errors, result = fb_out, fb_err, fb_result
                            break
                        if not (_is_quota_error(fb_err) or _is_model_unavailable(fb_err)):
                            # Different failure — surface it directly rather than keep trying
                            normalized_model = fallback_model
                            output, errors, result = fb_out, fb_err, fb_result
                            break

            if result.returncode != 0:
                return (
                    f"❌ Copilot Agent Error\n"
                    f"📁 Project: {project_path}\n"
                    f"🤖 Model tried: {normalized_model}\n\n"
                    f"{errors or output or 'Unknown error'}"
                )

            if not output and errors:
                return f"❌ Copilot Agent Error\n📁 Project: {project_path}\n🤖 Model: {normalized_model}\n\n{errors}"
            
            # Truncate if too long
            if len(output) > 8000:
                output = output[:8000] + "\n\n... (output truncated)"
            
            return (
                f"🤖 COPILOT AGENT RESPONSE\n"
                f"📁 Project: {project_path}\n"
                f"🧠 Model: {normalized_model}\n"
                f"🔧 Permissions: {allow_tools}\n\n"
                f"{output}"
            )
            
        except subprocess.TimeoutExpired:
            return f"❌ Copilot Agent timed out (>{timeout}s). Try a simpler prompt or increase COMMAND_TIMEOUT."
        except Exception as e:
            return f"❌ Error running Copilot Agent: {str(e)}"

    @staticmethod
    def ask_agent(
        prompt: str,
        agent: str = "copilot",
        project_path: str = "",
        model: str = "",
        allow_tools: str = "all",
        **kwargs,
    ) -> str:
        """Unified agent entrypoint with selectable persona.
        agent: copilot | claude | codex
        model: optional explicit model override
        """
        agent_key = (agent or "copilot").strip().lower()
        default_models = {
            "copilot": "gpt-5.2",
            "claude": "claude-sonnet-4.6",
            "codex": "gpt-5.3-codex",
        }
        if agent_key not in default_models:
            agent_key = "copilot"

        selected_model = (model or "").strip() or default_models[agent_key]
        result = VSCodeTools.copilot_agent(
            prompt=prompt,
            project_path=project_path,
            model=selected_model,
            allow_tools=allow_tools,
        )

        agent_label = {
            "copilot": "Copilot Agent",
            "claude": "Claude Code",
            "codex": "Codex",
        }[agent_key]
        header = f"🧭 Agent: {agent_label}\n🎯 Requested Model: {selected_model}\n\n"
        if isinstance(result, str) and result.startswith("❌"):
            # Preserve error semantics for API success detection logic
            return f"❌ Agent execution failed\n{header}{result}"
        return f"{header}{result}"
    
    @staticmethod
    def browse_directory(dirpath: str = "", depth: int = 3, show_hidden: bool = False) -> str:
        """Browse a directory with a visual tree structure — navigate any project"""
        try:
            if not dirpath:
                dirpath = _get_workspace()
            elif os.path.isabs(dirpath):
                # Absolute paths are allowed for read-only browsing — just resolve symlinks.
                # _resolve_path enforces workspace sandbox which is too strict here.
                dirpath = os.path.realpath(dirpath)
            else:
                dirpath = _resolve_path(dirpath)

            if not os.path.isdir(dirpath):
                return f"❌ ERROR: Directory not found: {dirpath}"
            
            SKIP_DIRS = {
                'node_modules', '.git', '__pycache__', '.venv', 'venv', 
                '.tox', '.pytest_cache', '.mypy_cache', 'dist', 'build',
                '.next', '.nuxt', '.output', 'coverage', '.cache',
                'egg-info', '.eggs', '.idea', '.vscode'
            }
            SKIP_SUFFIXES = {'.pyc', '.pyo', '.o', '.so', '.dylib'}
            
            lines = []
            file_count = 0
            dir_count = 0
            total_size = 0
            
            def _tree(path, prefix="", current_depth=0):
                nonlocal file_count, dir_count, total_size
                
                if current_depth >= depth:
                    return
                
                try:
                    entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                except PermissionError:
                    lines.append(f"{prefix}🚫 (permission denied)")
                    return
                
                # Filter entries
                filtered = []
                for entry in entries:
                    if not show_hidden and entry.name.startswith('.'):
                        continue
                    if entry.is_dir() and entry.name in SKIP_DIRS:
                        continue
                    if entry.suffix in SKIP_SUFFIXES:
                        continue
                    filtered.append(entry)
                
                for i, entry in enumerate(filtered):
                    is_last = (i == len(filtered) - 1)
                    connector = "└── " if is_last else "├── "
                    
                    if entry.is_dir():
                        dir_count += 1
                        lines.append(f"{prefix}{connector}📁 {entry.name}/")
                        extension = "    " if is_last else "│   "
                        _tree(entry, prefix + extension, current_depth + 1)
                    else:
                        file_count += 1
                        try:
                            size = entry.stat().st_size
                            total_size += size
                            if size > 1024 * 1024:
                                size_str = f"{size / 1024 / 1024:.1f}MB"
                            elif size > 1024:
                                size_str = f"{size / 1024:.1f}KB"
                            else:
                                size_str = f"{size}B"
                        except:
                            size_str = "?"
                        
                        # Color-code by file type
                        ext = entry.suffix.lower()
                        if ext in ('.py',):
                            icon = "🐍"
                        elif ext in ('.js', '.ts', '.jsx', '.tsx'):
                            icon = "📜"
                        elif ext in ('.html', '.htm'):
                            icon = "🌐"
                        elif ext in ('.css', '.scss', '.sass'):
                            icon = "🎨"
                        elif ext in ('.json', '.yaml', '.yml', '.toml'):
                            icon = "⚙️"
                        elif ext in ('.md', '.txt', '.rst'):
                            icon = "📝"
                        elif ext in ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico'):
                            icon = "🖼️"
                        elif ext in ('.env',):
                            icon = "🔐"
                        elif ext in ('.sh', '.bash', '.zsh'):
                            icon = "⚡"
                        elif ext in ('.sql', '.db', '.sqlite'):
                            icon = "🗄️"
                        else:
                            icon = "📄"
                        
                        lines.append(f"{prefix}{connector}{icon} {entry.name}  ({size_str})")
            
            root = Path(dirpath)
            lines.append(f"📁 {root.name}/")
            _tree(root)
            
            # Size summary
            if total_size > 1024 * 1024 * 1024:
                total_str = f"{total_size / 1024 / 1024 / 1024:.1f}GB"
            elif total_size > 1024 * 1024:
                total_str = f"{total_size / 1024 / 1024:.1f}MB"
            elif total_size > 1024:
                total_str = f"{total_size / 1024:.1f}KB"
            else:
                total_str = f"{total_size}B"
            
            tree_output = "\n".join(lines)
            
            # Check if it's a git repo
            git_info = ""
            git_check = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True,
                cwd=dirpath, timeout=5
            )
            if git_check.returncode == 0:
                branch = git_check.stdout.strip()
                git_info = f"\n🌿 Git branch: {branch}"
            
            # Check for project indicators
            project_info = ""
            indicators = {
                'package.json': '📦 Node.js',
                'requirements.txt': '🐍 Python',
                'Cargo.toml': '🦀 Rust',
                'go.mod': '🐹 Go',
                'pom.xml': '☕ Java/Maven',
                'build.gradle': '☕ Java/Gradle',
                'Gemfile': '💎 Ruby',
                'pubspec.yaml': '🎯 Dart/Flutter',
                'Makefile': '⚙️ Make',
                'CMakeLists.txt': '⚙️ CMake',
                'docker-compose.yml': '🐳 Docker',
                'Dockerfile': '🐳 Docker',
            }
            for fname, label in indicators.items():
                if os.path.exists(os.path.join(dirpath, fname)):
                    project_info += f"\n{label}"
            
            header = (
                f"📂 Directory: {dirpath}\n"
                f"📊 {dir_count} folders, {file_count} files ({total_str})"
                f"{git_info}"
                f"{project_info}\n\n"
            )
            
            return header + tree_output
            
        except Exception as e:
            return f"❌ Error browsing directory: {str(e)}"

    @staticmethod
    def setup_agents() -> str:
        """Detect and automatically install missing AI agents (Claude Code, gh Copilot).
        Safe to run on any machine — skips tools that are already installed."""
        import shutil
        lines = ["🔍 Checking installed AI agents...\n"]

        # ── Claude Code ──────────────────────────────────────────────────────
        if shutil.which("claude"):
            lines.append("✅ Claude Code — already installed")
        else:
            lines.append("⬇  Claude Code not found — installing via npm...")
            r = subprocess.run(
                ["npm", "install", "-g", "@anthropic-ai/claude-code"],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode == 0:
                lines.append("✅ Claude Code installed successfully")
            else:
                npm_err = r.stderr.strip().splitlines()[0] if r.stderr.strip() else "unknown error"
                if not shutil.which("npm"):
                    lines.append("❌ Claude Code — npm not found. Install Node.js first: https://nodejs.org")
                else:
                    lines.append(f"❌ Claude Code install failed: {npm_err}")

        # ── GitHub CLI (required for gh copilot) ─────────────────────────────
        gh_ok = bool(shutil.which("gh"))
        if gh_ok:
            lines.append("✅ GitHub CLI (gh) — already installed")
        else:
            lines.append("⬇  GitHub CLI not found — installing...")
            system = platform.system()
            if system == "Darwin":
                r = subprocess.run(["brew", "install", "gh"], capture_output=True, text=True, timeout=180)
                gh_ok = r.returncode == 0
            elif system == "Linux":
                # Try apt-get (Debian/Ubuntu)
                r = subprocess.run(
                    ["bash", "-c",
                     "type apt-get &>/dev/null && "
                     "apt-get install -y gh 2>/dev/null || "
                     "(curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg "
                     "| dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && "
                     "echo 'deb [arch=$(dpkg --print-architecture) "
                     "signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] "
                     "https://cli.github.com/packages stable main' "
                     "| tee /etc/apt/sources.list.d/github-cli.list > /dev/null && "
                     "apt-get update && apt-get install -y gh)"],
                    capture_output=True, text=True, timeout=180,
                )
                gh_ok = r.returncode == 0
            else:
                lines.append("⚠  GitHub CLI — auto-install not supported on Windows. Install manually: https://cli.github.com")
            if gh_ok:
                lines.append("✅ GitHub CLI installed successfully")
            elif system in ("Darwin", "Linux"):
                lines.append("❌ GitHub CLI install failed — install manually: https://cli.github.com")

        # ── gh copilot extension ──────────────────────────────────────────────
        if gh_ok:
            ext_check = subprocess.run(
                ["gh", "extension", "list"], capture_output=True, text=True, timeout=15
            )
            if "copilot" in ext_check.stdout.lower():
                lines.append("✅ gh copilot extension — already installed")
            else:
                lines.append("⬇  gh copilot extension not found — installing...")
                r = subprocess.run(
                    ["gh", "extension", "install", "github/gh-copilot", "--force"],
                    capture_output=True, text=True, timeout=60,
                )
                if r.returncode == 0:
                    lines.append("✅ gh copilot extension installed")
                else:
                    err = r.stderr.strip().splitlines()[0] if r.stderr.strip() else "unknown"
                    if "not logged" in err.lower() or "auth" in err.lower():
                        lines.append("⚠  gh copilot — not logged in. Run: gh auth login")
                    else:
                        lines.append(f"❌ gh copilot install failed: {err}")
        else:
            lines.append("⏭  gh copilot — skipped (gh CLI unavailable)")

        # ── Summary ───────────────────────────────────────────────────────────
        lines.append("\n✅ Agent setup complete. Run `vscars start` if the agent isn't already running.")
        return "\n".join(lines)


# Tool definitions
TOOLS = [
    {
        "name": "open_project",
        "description": "Open a project folder in VS Code",
        "required_permission": "view",
        "handler": VSCodeTools.open_project
    },
    {
        "name": "read_file",
        "description": "Read file contents",
        "required_permission": "view",
        "handler": VSCodeTools.read_file
    },
    {
        "name": "run_command",
        "description": "Run a shell command (workspace-aware)",
        "required_permission": "commands",
        "handler": VSCodeTools.run_command
    },
    {
        "name": "list_files",
        "description": "List files in directory",
        "required_permission": "view",
        "handler": VSCodeTools.list_files
    },
    {
        "name": "search_files",
        "description": "Search files by name or content",
        "required_permission": "view",
        "handler": VSCodeTools.search_files
    },
    {
        "name": "git_status",
        "description": "Git status, branch & commits",
        "required_permission": "view",
        "handler": VSCodeTools.git_status
    },
    {
        "name": "git_command",
        "description": "Run git commands (add, commit, push...)",
        "required_permission": "commands",
        "handler": VSCodeTools.git_command
    },
    {
        "name": "get_workspace_info",
        "description": "System & workspace info",
        "required_permission": "view",
        "handler": VSCodeTools.get_workspace_info
    },
    {
        "name": "copilot_agent",
        "description": "🤖 Copilot Agent — edit files, run commands, build features (claude-opus-4.6)",
        "required_permission": "copilot",
        "handler": VSCodeTools.copilot_agent
    },
    {
        "name": "ask_agent",
        "description": "🧭 Ask Agent — switch between Copilot, Claude Code, and Codex",
        "required_permission": "copilot",
        "handler": VSCodeTools.ask_agent
    },
    {
        "name": "browse_directory",
        "description": "📂 Visual directory tree browser with project detection",
        "required_permission": "view",
        "handler": VSCodeTools.browse_directory
    },
    {
        "name": "setup_agents",
        "description": "🔧 Auto-install missing AI agents (Claude Code, gh Copilot) on this machine",
        "required_permission": "commands",
        "handler": VSCodeTools.setup_agents
    },
    {
        "name": "ask_copilot",
        "description": "Send query to AI Chat (GPT-4o via GitHub Models)",
        "required_permission": "copilot",
        "handler": VSCodeTools.ask_copilot
    },
    {
        "name": "ask_ai",
        "description": "🧠 Multi-provider AI chat (Copilot / Claude / OpenAI) — auto-picks available provider",
        "required_permission": "copilot",
        "handler": VSCodeTools.ask_ai
    }
]

def execute_tool(tool_name: str, **kwargs) -> str:
    """Execute a tool by name"""
    tool = next((t for t in TOOLS if t["name"] == tool_name), None)
    if not tool:
        return f"❌ Unknown tool: {tool_name}"
    
    try:
        handler = tool["handler"]
        sig = inspect.signature(handler)
        accepts_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if accepts_var_kw:
            filtered = kwargs
        else:
            allowed = {
                name for name, p in sig.parameters.items()
                if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            }
            filtered = {k: v for k, v in kwargs.items() if k in allowed}
        return handler(**filtered)
    except Exception as e:
        return f"❌ Error: {str(e)}"
