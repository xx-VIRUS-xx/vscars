import subprocess
import os
import json
import requests
from pathlib import Path
from app.config import GITHUB_TOKEN, COPILOT_MODEL
from app.tools import _get_workspace

# Paths outside HOME are not accessible via git ops
_HOME = Path.home()

def _safe_repo_path(repo_path: str | None) -> str:
    """Resolve and validate a repo path. Must be under HOME and must exist."""
    if repo_path:
        resolved = Path(repo_path).expanduser().resolve()
        # Prevent traversal outside user's home directory
        try:
            resolved.relative_to(_HOME)
        except ValueError:
            raise ValueError(f"repo_path must be inside home directory ({_HOME})")
        if not resolved.is_dir():
            raise ValueError(f"repo_path does not exist: {resolved}")
        return str(resolved)
    return _get_workspace()

def _run_git(args: list, cwd: str) -> dict:
    """Run a git command safely. Never uses shell=True."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd, capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip() or result.stderr.strip()
        return {"success": result.returncode == 0, "output": output}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "Git command timed out"}
    except FileNotFoundError:
        return {"success": False, "output": "git not found in PATH"}
    except ValueError as e:
        return {"success": False, "output": str(e)}
    except Exception as e:
        return {"success": False, "output": str(e)}

def git_status(repo_path: str = None) -> dict:
    cwd = _safe_repo_path(repo_path)
    return _run_git(["status", "--short", "--branch"], cwd)

def git_diff(repo_path: str = None, staged: bool = False) -> dict:
    cwd = _safe_repo_path(repo_path)
    args = ["diff", "--stat"] if not staged else ["diff", "--cached", "--stat"]
    stat = _run_git(args, cwd)
    diff_args = ["diff"] if not staged else ["diff", "--cached"]
    full_diff = _run_git(diff_args + ["--unified=3"], cwd)
    combined = stat["output"] + "\n\n" + full_diff["output"]
    return {"success": stat["success"] or full_diff["success"], "output": combined.strip()}

def git_stage(files: list, repo_path: str = None) -> dict:
    """Stage specific files or all with ['.']"""
    cwd = _safe_repo_path(repo_path)
    return _run_git(["add"] + files, cwd)

def git_unstage(files: list, repo_path: str = None) -> dict:
    cwd = _safe_repo_path(repo_path)
    return _run_git(["reset", "HEAD", "--"] + files, cwd)

def git_commit(message: str, repo_path: str = None) -> dict:
    cwd = _safe_repo_path(repo_path)
    if not message or not message.strip():
        return {"success": False, "output": "Commit message cannot be empty"}
    return _run_git(["commit", "-m", message], cwd)

def git_push(remote: str = "origin", branch: str = "", repo_path: str = None) -> dict:
    cwd = _safe_repo_path(repo_path)
    args = ["push", remote]
    if branch:
        args.append(branch)
    return _run_git(args, cwd)

def git_log(n: int = 10, repo_path: str = None) -> dict:
    cwd = _safe_repo_path(repo_path)
    return _run_git(["log", f"--max-count={n}", "--oneline", "--graph"], cwd)

def git_branches(repo_path: str = None) -> dict:
    cwd = _safe_repo_path(repo_path)
    return _run_git(["branch", "-a", "--sort=-committerdate"], cwd)

def git_ai_commit_message(repo_path: str = None) -> dict:
    """Generate an AI commit message from staged diff using GitHub Copilot/OpenAI API."""
    cwd = _safe_repo_path(repo_path)
    diff_result = _run_git(["diff", "--cached"], cwd)
    diff_text = diff_result["output"]

    if not diff_text.strip():
        return {"success": False, "output": "No staged changes found. Stage files first."}

    # Truncate huge diffs
    if len(diff_text) > 6000:
        diff_text = diff_text[:6000] + "\n... (truncated)"

    if not GITHUB_TOKEN:
        # Fallback: generate a basic message from the diff
        lines = [l for l in diff_text.split('\n') if l.startswith('+') and not l.startswith('+++')]
        return {
            "success": True,
            "output": f"chore: update {len(lines)} lines (set GITHUB_TOKEN for AI messages)"
        }

    try:
        prompt = f"""Generate a concise, conventional commit message for these changes.
Format: <type>(<scope>): <description>
Types: feat, fix, refactor, docs, style, test, chore
Keep it under 72 chars. Return ONLY the commit message, nothing else.

Diff:
{diff_text}"""

        response = requests.post(
            "https://models.inference.ai.azure.com/chat/completions",
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
            json={
                "model": COPILOT_MODEL or "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100, "temperature": 0.3
            },
            timeout=15
        )
        if response.status_code == 200:
            msg = response.json()["choices"][0]["message"]["content"].strip().strip('"\'')
            return {"success": True, "output": msg}
        return {"success": False, "output": f"AI API error {response.status_code}"}
    except Exception as e:
        return {"success": False, "output": f"AI request failed: {e}"}
