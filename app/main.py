from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import asyncio
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from app.database import init_db, get_db, SessionLocal, User, UserPermission, CommandLog, ConversationHistory, PasswordResetToken, IdeaNote, UserSession, RegisteredMachine, TrustPolicy, ToolApproval, ScrumItem, AgentTask, AgentSession, AgentSessionMessage
from app.git_ops import git_status, git_diff, git_stage, git_unstage, git_commit, git_push, git_log, git_branches, git_ai_commit_message
import hashlib as _hashlib
from app.schemas import (
    UserRegister, UserLogin, Token, UserResponse, PermissionResponse,
    ToolInput, ToolResult
)
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, decode_token
)
from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES, SUPERUSER_PHONE, STATIC_DIR,
    MAX_REQUEST_SIZE, RATE_LIMIT_LOGIN, RATE_LIMIT_API, APP_BASE_URL
)
from app.tools import execute_tool, TOOLS, _reset_allowed_roots, _get_workspace
from app import relay as _relay
from app.billing.routes import billing_router
from app.email import send_welcome, send_password_reset
from app.billing.plan_limits import apply_plan_to_permissions, enforce_plan_limits
from app.trust import (
    DEFAULT_POLICY,
    normalize_policy_row,
    apply_profile_defaults,
    evaluate_request,
    request_fingerprint,
)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
import json
import re
import shlex
import threading
import time

# Initialize database
init_db()
_SCRUM_RUNNERS = {}
_SCRUM_RUNNER_LOCK = threading.Lock()
_VSCARS_ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None  # set on startup; used by background threads to relay calls

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Create FastAPI app
app = FastAPI(
    title="VSCARS",
    description="Control VS Code and Copilot from your mobile device worldwide",
    version="1.0.0"
)

@app.on_event("startup")
async def _capture_event_loop():
    global _MAIN_LOOP
    _MAIN_LOOP = asyncio.get_event_loop()

# Rate limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Billing router
app.include_router(billing_router)

# Trust proxy headers from Cloudflare Tunnel (runs on 127.0.0.1)
# This makes request.url.scheme and client IP reflect the real values
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="127.0.0.1")

# CORS — restrict to known origins
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-VSCARS-Key"],
)

# Security headers on every response
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # HSTS only when FORCE_HTTPS is set (i.e. deployed behind TLS)
    if os.getenv("FORCE_HTTPS", "false").lower() == "true":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    return response

# Request size limiter middleware
@app.middleware("http")
async def limit_request_size(request: Request, call_next):
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > MAX_REQUEST_SIZE:
        return JSONResponse({"detail": "Request too large"}, status_code=413)
    return await call_next(request)

# Mount static files AFTER creating app
if os.path.exists(STATIC_DIR):
    try:
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
        print(f"✅ Static files mounted from: {STATIC_DIR}")
    except Exception as e:
        print(f"⚠️ Warning: Could not mount static files: {e}")
else:
    print(f"⚠️ Warning: Static directory not found at {STATIC_DIR}")

# ==================== AUTH ROUTES ====================

@app.post("/api/auth/register", response_model=Token)
@limiter.limit(RATE_LIMIT_LOGIN)
async def register(request: Request, user_data: UserRegister, db: Session = Depends(get_db)):
    """Register a new user"""
    # Check if user exists
    existing_user = db.query(User).filter(
        (User.username == user_data.username) | 
        (User.email == user_data.email)
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered"
        )
    
    # Password strength validation
    if len(user_data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )
    
    # Email format validation
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format"
        )
    
    # Username validation
    if not re.match(r'^[a-zA-Z0-9_-]{3,30}$', user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3-30 chars, letters/numbers/hyphens/underscores only"
        )
    
    # SECURITY: Only the FIRST user gets superuser. All others are regular users.
    user_count = db.query(User).count()
    is_first_user = (user_count == 0)
    
    import secrets as _secrets
    device_id = user_data.device_id or f"web-{_secrets.token_hex(8)}"

    new_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        device_id=device_id,
        is_superuser=is_first_user,
        is_active=True,
        plan="beta",
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Set permissions and auto-issue API key for every new user
    apply_plan_to_permissions(new_user, db)
    if not new_user.api_key_hash:
        from app.billing.plan_limits import issue_api_key
        issue_api_key(new_user, db)

    # Welcome email (non-blocking — ignore failure)
    try:
        send_welcome(new_user.email, new_user.username)
    except Exception:
        pass
    
    # Create token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": new_user.username},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "email": new_user.email,
            "is_superuser": new_user.is_superuser
        }
    }

@app.post("/api/auth/login", response_model=Token)
@limiter.limit(RATE_LIMIT_LOGIN)
async def login(request: Request, user_data: UserLogin, db: Session = Depends(get_db)):
    """Login user"""
    user = db.query(User).filter(User.username == user_data.username).first()
    
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive"
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser
        }
    }

@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user info"""
    perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "device_id": current_user.device_id,
        "is_superuser": current_user.is_superuser,
        "is_active": current_user.is_active,
        "plan": current_user.plan or "beta",
        "can_run_copilot": bool(perm.can_run_copilot) if perm else False,
        "can_run_commands": bool(perm.can_run_commands) if perm else False,
        "can_edit_files": bool(perm.can_edit_files) if perm else False,
        "can_view_files": bool(perm.can_view_files) if perm else False,
        "daily_api_calls": current_user.daily_api_calls or 0,
        "trial_ends_at": current_user.trial_ends_at,
        "created_at": current_user.created_at,
    }

@app.post("/api/auth/logout")
async def logout(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Logout — revoke current token so it can't be reused"""
    from app.auth import revoke_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        revoke_token(token, current_user.id, db)
    return {"message": "Logged out successfully"}


@app.post("/api/auth/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(request: Request, data: dict, db: Session = Depends(get_db)):
    """Send password reset email. Always returns 200 to avoid email enumeration."""
    import secrets as _sec
    email = data.get("email", "").strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        # Invalidate any existing tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False
        ).update({"used": True})

        token = _sec.token_urlsafe(32)
        record = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(record)
        db.commit()

        from app.config import APP_BASE_URL
        reset_url = f"{APP_BASE_URL}/?reset_token={token}"
        send_password_reset(user.email, reset_url)

    return {"message": "If that email is registered, you'll receive a reset link shortly."}


@app.post("/api/auth/reset-password")
async def reset_password(data: dict, db: Session = Depends(get_db)):
    """Consume a reset token and update password."""
    token = data.get("token", "").strip()
    new_password = data.get("new_password", "")

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    record = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token,
        PasswordResetToken.used == False,
        PasswordResetToken.expires_at > datetime.utcnow(),
    ).first()

    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link. Please request a new one.")

    user = db.query(User).filter(User.id == record.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    user.hashed_password = hash_password(new_password)
    record.used = True
    db.commit()
    return {"message": "Password reset successfully. You can now sign in."}

# ==================== TOOL ROUTES ====================

def _get_or_create_trust_policy(user_id: int, db: Session) -> TrustPolicy:
    policy_row = db.query(TrustPolicy).filter(TrustPolicy.user_id == user_id).first()
    if policy_row:
        return policy_row
    policy_row = TrustPolicy(
        user_id=user_id,
        profile=DEFAULT_POLICY["profile"],
        require_approval=DEFAULT_POLICY["require_approval"],
        block_destructive=DEFAULT_POLICY["block_destructive"],
        allow_network=DEFAULT_POLICY["allow_network"],
        kill_switch=DEFAULT_POLICY["kill_switch"],
        allowed_command_prefixes=DEFAULT_POLICY["allowed_command_prefixes"],
        updated_at=datetime.utcnow(),
    )
    db.add(policy_row)
    db.commit()
    db.refresh(policy_row)
    return policy_row

_ASYNC_AGENT_TOOLS = set()  # ask_agent and copilot_agent now relay to user's Mac via executor
_TOOL_CONTROL_FIELDS = {"async", "wait", "agent_session_id", "continue_session", "session_name"}

def _ensure_copilot_permission(current_user: User, db: Session):
    """Raise 403 when user cannot run copilot/agent tools."""
    if current_user.is_superuser:
        return
    perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
    if not perm or not perm.can_run_copilot:
        raise HTTPException(status_code=403, detail="Copilot permission required")


def _crawler_url_from_request(request: Request, task_id: int) -> str:
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/agent/tasks/{task_id}"


def _ensure_agent_session(
    db: Session,
    user_id: int,
    requested_session_id,
    agent: str,
    model: str,
    project_path: str,
    allow_tools: str,
    session_name: str = "",
):
    session = None
    if requested_session_id not in (None, "", 0, "0"):
        try:
            sid = int(requested_session_id)
            session = db.query(AgentSession).filter(
                AgentSession.id == sid,
                AgentSession.user_id == user_id,
                AgentSession.is_active == True
            ).first()
        except Exception:
            session = None

    if not session:
        session = AgentSession(
            user_id=user_id,
            name=(session_name or "").strip() or f"{(agent or 'copilot').strip().lower()} session",
            agent=(agent or "copilot").strip().lower(),
            model=(model or "").strip() or None,
            project_path=(project_path or "").strip() or None,
            allow_tools=(allow_tools or "all").strip() or "all",
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def _build_session_prompt(db: Session, session_id: int, user_prompt: str, max_msgs: int = 8) -> str:
    messages = db.query(AgentSessionMessage).filter(
        AgentSessionMessage.session_id == session_id
    ).order_by(AgentSessionMessage.created_at.desc()).limit(max(1, max_msgs)).all()
    if not messages:
        return user_prompt

    lines = ["Conversation context (most recent first):"]
    for m in reversed(messages):
        role = "User" if m.role == "user" else ("Assistant" if m.role == "assistant" else "System")
        text = (m.content or "").strip()
        if text:
            lines.append(f"{role}: {text}")
    lines.append("")
    lines.append(f"Current user request: {user_prompt}")
    return "\n".join(lines)


def _get_scrum_runner_state(user_id: int) -> dict:
    with _SCRUM_RUNNER_LOCK:
        current = _SCRUM_RUNNERS.get(user_id)
        if not current:
            current = {
                "running": False,
                "stop_requested": False,
                "current_agent_task_id": None,
                "current_scrum_item_id": None,
                "last_error": "",
                "completed_count": 0,
                "started_at": None,
                "config": {
                    "project_path": "",
                    "allow_tools": "read",
                    "allow_self_work": False,
                },
            }
            _SCRUM_RUNNERS[user_id] = current
        return dict(current)


def _update_scrum_runner_state(user_id: int, **updates) -> dict:
    with _SCRUM_RUNNER_LOCK:
        current = _SCRUM_RUNNERS.get(user_id) or {
            "running": False,
            "stop_requested": False,
            "current_agent_task_id": None,
            "current_scrum_item_id": None,
            "last_error": "",
            "completed_count": 0,
            "started_at": None,
            "config": {
                "project_path": "",
                "allow_tools": "read",
                "allow_self_work": False,
            },
        }
        current.update(updates)
        _SCRUM_RUNNERS[user_id] = current
        return dict(current)


def _normalize_runner_project_path(project_path: str) -> str:
    # Path lives on the user's Mac — don't validate against EC2 filesystem.
    # Just normalise ~ and return as-is; the Mac executor enforces its own sandbox.
    raw = (project_path or "").strip()
    if not raw:
        return ""
    return os.path.expanduser(raw)


def _validate_runner_target(project_path: str, allow_self_work: bool) -> str:
    resolved = _normalize_runner_project_path(project_path)
    if not resolved:
        raise ValueError("Target project path is required for autonomous mode.")
    return resolved


def _pick_next_scrum_task(db: Session, user_id: int):
    stories = db.query(ScrumItem).filter(
        ScrumItem.user_id == user_id,
        ScrumItem.item_type == "story",
        ScrumItem.status == "in_progress",
    ).all()
    in_progress_story_ids = {s.id for s in stories}

    tasks = db.query(ScrumItem).filter(
        ScrumItem.user_id == user_id,
        ScrumItem.item_type == "task",
        ScrumItem.status.in_(["backlog", "todo"]),
    ).all()
    if not tasks:
        return None

    def sort_key(item: ScrumItem):
        story_bias = 0 if item.parent_id in in_progress_story_ids else 1
        priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get((item.priority or "medium").lower(), 2)
        backlog_penalty = 1 if item.status == "backlog" else 0
        return (story_bias, priority_rank, backlog_penalty, item.created_at or datetime.utcnow(), item.id)

    tasks.sort(key=sort_key)
    return tasks[0]


def _build_scrum_runner_prompt(item: ScrumItem, parent_story, target_path: str) -> str:
    lines = [
        "You are the VSCARS autonomous scrum runner.",
        f"Target project path: {target_path}",
        f"Scrum task #{item.id}: {item.title}",
    ]
    if parent_story:
        lines.append(f"Parent story: #{parent_story.id} - {parent_story.title}")
        if parent_story.description:
            lines.append(f"Story context: {parent_story.description}")
    if item.description:
        lines.append(f"Task details: {item.description}")
    if item.tags:
        lines.append(f"Tags: {item.tags}")
    lines.extend([
        "",
        "Work only inside the target project path.",
        "Do not touch the VSCARS app unless explicitly allowed.",
        "Make the smallest complete change that satisfies the scrum task.",
        "Return a concise summary of what changed and any follow-up risks.",
    ])
    return "\n".join(lines)


def _ensure_scrum_runner_session(db: Session, user_id: int, project_path: str, allow_tools: str):
    session = db.query(AgentSession).filter(
        AgentSession.user_id == user_id,
        AgentSession.name == "Scrum Runner",
        AgentSession.is_active == True
    ).order_by(AgentSession.updated_at.desc()).first()
    if not session:
        session = AgentSession(
            user_id=user_id,
            name="Scrum Runner",
            agent="copilot",
            model=None,
            project_path=project_path,
            allow_tools=allow_tools or "read",
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session
    session.project_path = project_path
    session.allow_tools = allow_tools or session.allow_tools or "read"
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return session


def _run_scrum_runner(user_id: int):
    while True:
        state = _get_scrum_runner_state(user_id)
        if not state.get("running"):
            return
        if state.get("stop_requested"):
            _update_scrum_runner_state(
                user_id,
                running=False,
                stop_requested=False,
                current_agent_task_id=None,
                current_scrum_item_id=None,
            )
            return

        db = SessionLocal()
        try:
            current_task_id = state.get("current_agent_task_id")
            if current_task_id:
                task = db.query(AgentTask).filter(
                    AgentTask.id == current_task_id,
                    AgentTask.user_id == user_id,
                ).first()
                if task and task.status in {"queued", "running"}:
                    time.sleep(2)
                    continue
                if task and task.scrum_item_id:
                    scrum_item = db.query(ScrumItem).filter(
                        ScrumItem.id == task.scrum_item_id,
                        ScrumItem.user_id == user_id,
                    ).first()
                    if scrum_item:
                        scrum_item.status = "review" if task.status == "completed" else "todo"
                        scrum_item.updated_at = datetime.utcnow()
                        db.commit()
                if task and task.status == "completed":
                    _update_scrum_runner_state(
                        user_id,
                        current_agent_task_id=None,
                        current_scrum_item_id=None,
                        completed_count=int(state.get("completed_count") or 0) + 1,
                    )
                    time.sleep(1)
                    continue
                if task and task.status == "failed":
                    _update_scrum_runner_state(
                        user_id,
                        current_agent_task_id=None,
                        current_scrum_item_id=None,
                        last_error=(task.error or "Autonomous scrum task failed")[:500],
                    )
                    time.sleep(1)
                    continue

            config = state.get("config") or {}
            target_path = _validate_runner_target(config.get("project_path", ""), bool(config.get("allow_self_work")))
            next_item = _pick_next_scrum_task(db, user_id)
            if not next_item:
                _update_scrum_runner_state(
                    user_id,
                    running=False,
                    current_agent_task_id=None,
                    current_scrum_item_id=None,
                )
                return

            parent_story = None
            if next_item.parent_id:
                parent_story = db.query(ScrumItem).filter(
                    ScrumItem.id == next_item.parent_id,
                    ScrumItem.user_id == user_id,
                ).first()

            session = _ensure_scrum_runner_session(db, user_id, target_path, str(config.get("allow_tools") or "read"))
            prompt = _build_scrum_runner_prompt(next_item, parent_story, target_path)
            db.add(AgentSessionMessage(session_id=session.id, role="user", content=prompt[:8000]))
            next_item.status = "in_progress"
            next_item.updated_at = datetime.utcnow()
            session.updated_at = datetime.utcnow()
            db.commit()

            task = AgentTask(
                user_id=user_id,
                tool_name="ask_agent",
                input_params=json.dumps({
                    "prompt": prompt,
                    "agent": session.agent or "copilot",
                    "project_path": target_path,
                    "model": session.model or "",
                    "allow_tools": session.allow_tools or "read",
                }),
                status="queued",
                created_at=datetime.utcnow(),
                agent_session_id=session.id,
                scrum_item_id=next_item.id,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            threading.Thread(target=_run_relay_agent_task, args=(task.id, user_id, None, _MAIN_LOOP), daemon=True).start()
            _update_scrum_runner_state(
                user_id,
                current_agent_task_id=task.id,
                current_scrum_item_id=next_item.id,
                last_error="",
            )
        except Exception as exc:
            _update_scrum_runner_state(
                user_id,
                running=False,
                current_agent_task_id=None,
                current_scrum_item_id=None,
                last_error=str(exc)[:500],
            )
            return
        finally:
            db.close()
        time.sleep(1)


def _run_relay_agent_task(task_id: int, user_id: int, machine_id: str | None, loop: asyncio.AbstractEventLoop = None):
    """Background runner for ask_agent / copilot_agent — relays to user's Mac via WebSocket.

    Must be called from a daemon thread. Pass the uvicorn event loop so
    run_coroutine_threadsafe can schedule the relay call on the correct loop
    (the one that owns the WebSocket connection and _pending futures).
    """
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if not task:
            return

        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()

        params = json.loads(task.input_params or "{}")

        _loop = loop or _MAIN_LOOP
        if _loop is None:
            result = "❌ Relay error: event loop not available"
            success = False
        else:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    _relay.call_tool(user_id, machine_id, task.tool_name, params, timeout=180.0),
                    _loop,
                )
                result_data = future.result(timeout=185)
                result = result_data.get("result", "")
                success = result_data.get("success", True)
            except Exception as e:
                result = f"❌ Relay error: {e}"
                success = False

        task.status = "completed" if success else "failed"
        task.result = str(result)[:20000]
        task.error = None if success else str(result)[:20000]
        task.finished_at = datetime.utcnow()
        db.commit()

        if task.agent_session_id:
            session = db.query(AgentSession).filter(
                AgentSession.id == task.agent_session_id,
                AgentSession.user_id == task.user_id
            ).first()
            if session:
                db.add(AgentSessionMessage(
                    session_id=session.id, role="assistant",
                    content=(task.result or task.error or "")[:12000],
                ))
                session.updated_at = datetime.utcnow()
                session.last_task_id = task.id
                db.commit()

        db.add(CommandLog(
            user_id=task.user_id, tool_name=task.tool_name,
            action=f"Relay task #{task.id} finished",
            input_params=task.input_params,
            result=(task.result or task.error or "")[:500],
            status="success" if success else "error",
            device_id="relay-worker",
        ))
        db.commit()
    except Exception as e:
        try:
            task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
            if task:
                task.status = "failed"
                task.error = f"❌ Relay task error: {e}"[:20000]
                task.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _run_agent_task(task_id: int):
    """Background runner for long agent jobs."""
    db = SessionLocal()
    try:
        task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
        if not task:
            return

        task.status = "running"
        task.started_at = datetime.utcnow()
        db.commit()

        params = json.loads(task.input_params or "{}")
        result = execute_tool(task.tool_name, **params)
        success = not str(result).startswith("❌")

        task.status = "completed" if success else "failed"
        task.result = str(result)[:20000]
        task.error = None if success else str(result)[:20000]
        task.finished_at = datetime.utcnow()
        db.commit()

        if task.agent_session_id:
            session = db.query(AgentSession).filter(
                AgentSession.id == task.agent_session_id,
                AgentSession.user_id == task.user_id
            ).first()
            if session:
                assistant_msg = AgentSessionMessage(
                    session_id=session.id,
                    role="assistant",
                    content=(task.result or task.error or "")[:12000],
                )
                session.updated_at = datetime.utcnow()
                session.last_task_id = task.id
                db.add(assistant_msg)
                db.commit()

        log_entry = CommandLog(
            user_id=task.user_id,
            tool_name=task.tool_name,
            action=f"Async task #{task.id} finished",
            input_params=task.input_params,
            result=(task.result or task.error or "")[:500],
            status="success" if success else "error",
            device_id="background-worker",
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        try:
            task = db.query(AgentTask).filter(AgentTask.id == task_id).first()
            if task:
                task.status = "failed"
                task.error = f"❌ Background task error: {str(e)}"[:20000]
                task.finished_at = datetime.utcnow()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@app.get("/api/tools")
async def list_tools(current_user: User = Depends(get_current_user)):
    """List available tools with user's permissions"""
    tools_list = []
    
    for tool in TOOLS:
        tools_list.append({
            "name": tool["name"],
            "description": tool["description"],
            "permission_required": tool["required_permission"]
        })
    
    return {"tools": tools_list}

@app.post("/api/tools/execute", response_model=ToolResult)
async def execute_tool_endpoint(
    request: Request,
    tool_input: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Execute a tool"""
    tool_name = tool_input.get("tool")
    
    if not tool_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tool name is required"
        )
    
    # Find tool
    tool = next((t for t in TOOLS if t["name"] == tool_name), None)
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool not found: {tool_name}"
        )
    
    # Enforce plan daily limits (raises 429 if exceeded)
    enforce_plan_limits(current_user, db)

    # Check permissions
    if not current_user.is_superuser:
        permission = db.query(UserPermission).filter(
            UserPermission.user_id == current_user.id
        ).first()
        
        if not permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No permissions assigned"
            )
        
        # Check specific permission
        permission_map = {
            "copilot": permission.can_run_copilot,
            "commands": permission.can_run_commands,
            "edit": permission.can_edit_files,
            "view": permission.can_view_files,
        }
        
        if not permission_map.get(tool["required_permission"], False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for {tool_name}"
            )

    # Support both flat {"tool":"x","command":"y"} and nested {"tool":"x","params":{"command":"y"}}
    if "params" in tool_input and isinstance(tool_input["params"], dict):
        _raw = {**tool_input["params"], **{k: v for k, v in tool_input.items() if k not in ("tool", "params")}}
    else:
        _raw = tool_input
    params = {
        k: v for k, v in _raw.items()
        if k != "tool" and k not in _TOOL_CONTROL_FIELDS and v is not None
    }

    # Trust policy checks: kill switch, command guardrails, approval flow
    policy_row = _get_or_create_trust_policy(current_user.id, db)
    policy = apply_profile_defaults(normalize_policy_row(policy_row))
    allowed, blocked_reason, sensitive, sensitivity_reason = evaluate_request(policy, tool_name, params)

    if not allowed:
        blocked_msg_map = {
            "kill_switch_enabled": "Execution blocked: emergency kill switch is enabled.",
            "blocked_destructive_pattern": "Execution blocked by destructive-command protection policy.",
            "network_command_blocked": "Execution blocked: network commands are disabled in your policy.",
            "command_not_in_allowlist": "Execution blocked: command is not in your allowlist.",
        }
        blocked_msg = blocked_msg_map.get(blocked_reason, "Execution blocked by trust policy.")
        log_entry = CommandLog(
            user_id=current_user.id,
            tool_name=tool_name,
            action=f"Blocked by trust policy ({blocked_reason})",
            input_params=json.dumps(params),
            result=blocked_msg,
            status="blocked",
            device_id=current_user.device_id,
        )
        db.add(log_entry)
        db.commit()
        return {
            "success": False,
            "tool": tool_name,
            "error": blocked_msg,
        }

    # Long-running agent tools: run asynchronously by default and return tracker URL
    raw_async = tool_input.get("async", True)
    raw_wait = tool_input.get("wait", False)
    continue_session_raw = tool_input.get("continue_session", True)
    continue_session = continue_session_raw if isinstance(continue_session_raw, bool) else str(continue_session_raw).strip().lower() in {"1", "true", "yes", "on"}
    run_async = raw_async if isinstance(raw_async, bool) else str(raw_async).strip().lower() in {"1", "true", "yes", "on"}
    wait_for_result = raw_wait if isinstance(raw_wait, bool) else str(raw_wait).strip().lower() in {"1", "true", "yes", "on"}
    if tool_name in _ASYNC_AGENT_TOOLS and run_async and not wait_for_result:
        agent_session = None
        if tool_name == "ask_agent":
            user_prompt = str(params.get("prompt", "") or "").strip()
            if user_prompt:
                agent_session = _ensure_agent_session(
                    db=db,
                    user_id=current_user.id,
                    requested_session_id=tool_input.get("agent_session_id"),
                    agent=str(params.get("agent", "copilot") or "copilot"),
                    model=str(params.get("model", "") or ""),
                    project_path=str(params.get("project_path", "") or ""),
                    allow_tools=str(params.get("allow_tools", "all") or "all"),
                    session_name=str(tool_input.get("session_name", "") or ""),
                )
                # Session is source of truth for persona/model so execution
                # does not drift back to a default agent.
                params["agent"] = agent_session.agent or str(params.get("agent", "copilot") or "copilot")
                if agent_session.model:
                    params["model"] = agent_session.model
                if agent_session.project_path:
                    params["project_path"] = agent_session.project_path
                if agent_session.allow_tools:
                    params["allow_tools"] = agent_session.allow_tools
                session_prompt = _build_session_prompt(db, agent_session.id, user_prompt) if continue_session else user_prompt
                params["prompt"] = session_prompt
                db.add(AgentSessionMessage(session_id=agent_session.id, role="user", content=user_prompt[:8000]))
                agent_session.updated_at = datetime.utcnow()
                db.commit()

        task = AgentTask(
            user_id=current_user.id,
            tool_name=tool_name,
            input_params=json.dumps(params),
            status="queued",
            created_at=datetime.utcnow(),
            agent_session_id=agent_session.id if agent_session else None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        threading.Thread(target=_run_relay_agent_task, args=(task.id, current_user.id, tool_input.get("machine_id"), _MAIN_LOOP), daemon=True).start()

        crawl_url = _crawler_url_from_request(request, task.id)
        return {
            "success": True,
            "tool": tool_name,
            "status": "queued",
            "task_id": task.id,
            "agent_session_id": task.agent_session_id,
            "crawler_url": crawl_url,
            "result": (
                f"⏳ Task queued: #{task.id}\n"
                f"Track progress: {crawl_url}\n"
                f"You will get a notification when the task finishes."
            ),
        }

    # Permissions that require the tool to run on the user's own machine.
    # ask_agent / copilot_agent invoke CLIs (claude, gh copilot, codex) that only exist on the user's Mac.
    # ask_copilot / ask_ai are pure API calls — they run fine on the relay server.
    _MACHINE_PERMS = {"view", "edit", "commands"}
    _MACHINE_AGENT_TOOLS = {"ask_agent", "copilot_agent"}
    if tool_name in _MACHINE_AGENT_TOOLS:
        if not _relay.is_connected(current_user.id):
            return {
                "success": False, "tool": tool_name,
                "result": "❌ No machine connected. Run `vscars start` on your machine — agent CLIs (Claude Code, Copilot, Codex) run on your Mac.",
                "error": "no_machine", "approval_required": None, "approval_id": None,
                "task_id": None, "agent_session_id": None, "crawler_url": None, "status": None,
            }
        machine_id = tool_input.get("machine_id")

        # Ensure agent session exists for ask_agent so we can attach the task
        ma_session = None
        if tool_name == "ask_agent":
            user_prompt = str(params.get("prompt", "") or "").strip()
            if user_prompt:
                # Resolve project_path: use what the caller sent, or pull from the
                # machine's cached workspace so copilot_agent runs against the right dir.
                project_path = str(params.get("project_path", "") or "").strip()
                if not project_path:
                    try:
                        ws_cache = f"/tmp/vscars_ws_{current_user.id}.txt"
                        with open(ws_cache) as _f:
                            project_path = _f.read().strip()
                    except Exception:
                        project_path = ""

                ma_session = _ensure_agent_session(
                    db=db,
                    user_id=current_user.id,
                    requested_session_id=tool_input.get("agent_session_id"),
                    agent=str(params.get("agent", "copilot") or "copilot"),
                    model=str(params.get("model", "") or ""),
                    project_path=project_path,
                    allow_tools=str(params.get("allow_tools", "all") or "all"),
                    session_name=str(tool_input.get("session_name", "") or ""),
                )
                if ma_session.model:
                    params["model"] = ma_session.model
                # Always send project_path to the machine — use session value (never empty string)
                params["project_path"] = ma_session.project_path or project_path or ""
                if ma_session.allow_tools:
                    params["allow_tools"] = ma_session.allow_tools
                params["agent"] = ma_session.agent or params.get("agent", "copilot")
                if continue_session:
                    params["prompt"] = _build_session_prompt(db, ma_session.id, user_prompt)
                db.add(AgentSessionMessage(session_id=ma_session.id, role="user", content=user_prompt[:8000]))
                ma_session.updated_at = datetime.utcnow()
                db.commit()

        # Try for up to 5s; if still running, queue as a background task so the UI
        # gets a task ID immediately instead of showing a frozen loading screen.
        FAST_TIMEOUT = 5.0
        try:
            result_data = await asyncio.wait_for(
                _relay.call_tool(current_user.id, machine_id, tool_name, params, timeout=180.0),
                timeout=FAST_TIMEOUT,
            )
            # Completed fast — save assistant reply and return directly
            if ma_session:
                db.add(AgentSessionMessage(
                    session_id=ma_session.id, role="assistant",
                    content=str(result_data.get("result", ""))[:12000],
                ))
                ma_session.updated_at = datetime.utcnow()
                db.commit()
            return {
                "success": result_data.get("success", True),
                "tool": tool_name,
                "result": result_data.get("result", ""),
                "agent_session_id": ma_session.id if ma_session else None,
                "error": None, "approval_required": None, "approval_id": None,
                "task_id": None, "crawler_url": None, "status": None,
            }
        except ConnectionError as e:
            raise HTTPException(status_code=503, detail={"message": str(e), "code": "no_machine"})
        except asyncio.TimeoutError:
            pass  # Took longer than 5s — queue it

        # Queue as background relay task
        task = AgentTask(
            user_id=current_user.id,
            tool_name=tool_name,
            input_params=json.dumps(params),
            status="queued",
            created_at=datetime.utcnow(),
            agent_session_id=ma_session.id if ma_session else None,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        threading.Thread(
            target=_run_relay_agent_task,
            args=(task.id, current_user.id, machine_id, _MAIN_LOOP),
            daemon=True,
        ).start()
        crawl_url = _crawler_url_from_request(request, task.id)
        return {
            "success": True,
            "tool": tool_name,
            "status": "queued",
            "task_id": task.id,
            "agent_session_id": ma_session.id if ma_session else None,
            "crawler_url": crawl_url,
            "result": (
                f"⏳ Agent task queued: #{task.id}\n"
                f"Your agent is running on your Mac — this usually takes 30-120s.\n"
                f"Track progress: {crawl_url}\n"
                f"You will get a notification when it finishes."
            ),
            "error": None, "approval_required": None, "approval_id": None,
        }

    # All machine-permission tools must go through the relay.
    # If no machine is connected, return a clear error instead of running on the relay host.
    if tool["required_permission"] in _MACHINE_PERMS and not _relay.is_connected(current_user.id):
        return {
            "success": False, "tool": tool_name,
            "result": "❌ No machine connected. Run `vscars start` on your machine to enable this.",
            "error": "no_machine", "approval_required": None, "approval_id": None,
            "task_id": None, "agent_session_id": None, "crawler_url": None, "status": None,
        }

    if tool["required_permission"] in _MACHINE_PERMS and _relay.is_connected(current_user.id):
        machine_id = tool_input.get("machine_id")  # optional: target a specific machine
        try:
            result_data = await _relay.call_tool(
                current_user.id, machine_id, tool_name, params
            )
        except ConnectionError as e:
            raise HTTPException(status_code=503, detail={"message": str(e), "code": "no_machine"})
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail={"message": "Machine did not respond in time.", "code": "timeout"})
        success = result_data.get("success", True)
        result_str = result_data.get("result", "")
        log_entry = CommandLog(
            user_id=current_user.id, tool_name=tool_name,
            action=f"Relayed {tool_name}",
            input_params=json.dumps(params), result=str(result_str)[:500],
            status="success" if success else "error", device_id=current_user.device_id,
        )
        db.add(log_entry)
        db.commit()
        return {"success": success, "tool": tool_name, "result": result_str}

    # Execute tool (superuser: runs locally on host)
    try:
        params = {
            k: v for k, v in tool_input.items()
            if k != "tool" and k not in _TOOL_CONTROL_FIELDS and v is not None
        }
        sync_agent_session = None
        if tool_name == "ask_agent":
            user_prompt = str(params.get("prompt", "") or "").strip()
            if user_prompt:
                sync_agent_session = _ensure_agent_session(
                    db=db,
                    user_id=current_user.id,
                    requested_session_id=tool_input.get("agent_session_id"),
                    agent=str(params.get("agent", "copilot") or "copilot"),
                    model=str(params.get("model", "") or ""),
                    project_path=str(params.get("project_path", "") or ""),
                    allow_tools=str(params.get("allow_tools", "all") or "all"),
                    session_name=str(tool_input.get("session_name", "") or ""),
                )
                # Session is source of truth for persona/model so execution
                # does not drift back to a default agent.
                params["agent"] = sync_agent_session.agent or str(params.get("agent", "copilot") or "copilot")
                if sync_agent_session.model:
                    params["model"] = sync_agent_session.model
                if sync_agent_session.project_path:
                    params["project_path"] = sync_agent_session.project_path
                if sync_agent_session.allow_tools:
                    params["allow_tools"] = sync_agent_session.allow_tools
                if continue_session:
                    params["prompt"] = _build_session_prompt(db, sync_agent_session.id, user_prompt)
                db.add(AgentSessionMessage(session_id=sync_agent_session.id, role="user", content=user_prompt[:8000]))
                sync_agent_session.updated_at = datetime.utcnow()
                db.commit()

        # AI tools: check provider configured, then use ai_provider layer
        if tool_name in ("ask_ai", "ask_copilot"):
            from app import ai_provider
            if not ai_provider.has_ai_configured(db, current_user.id):
                return {
                    "success": False,
                    "tool": tool_name,
                    "result": "❌ No AI provider configured. Go to Settings → AI Keys to add your API key.",
                    "error": "no_ai_provider",
                }
            prompt = params.get("prompt") or params.get("query") or ""
            try:
                result = ai_provider.chat(db, current_user.id, [{"role": "user", "content": prompt}])
            except ValueError as _ve:
                result = f"❌ {_ve}"
            except Exception as _ae:
                result = f"❌ AI error: {_ae}"
        else:
            result = execute_tool(tool_name, **params)

        if sync_agent_session:
            db.add(AgentSessionMessage(
                session_id=sync_agent_session.id,
                role="assistant",
                content=str(result)[:12000]
            ))
            sync_agent_session.updated_at = datetime.utcnow()
            db.commit()

        # Log the command execution
        success = not result.startswith("❌")
        log_entry = CommandLog(
            user_id=current_user.id,
            tool_name=tool_name,
            action=f"Executed {tool_name}",
            input_params=json.dumps(params),
            result=result[:500],  # Limit to 500 chars
            status="success" if success else "error",
            device_id=current_user.device_id
        )
        db.add(log_entry)

        # Save conversation history for ask_copilot and ask_ai
        if tool_name in ("ask_copilot", "ask_ai"):
            query = params.get("query", "") or params.get("prompt", "")
            conversation = ConversationHistory(
                user_id=current_user.id,
                query=query,
                response=result,
                tool_used=tool_name,
                status="success" if success else "error",
                device_id=current_user.device_id
            )
            db.add(conversation)

        db.commit()

        return {
            "success": success,
            "tool": tool_name,
            "result": result,
            "agent_session_id": sync_agent_session.id if sync_agent_session else None,
        }
    except Exception as e:
        # Log the error
        log_entry = CommandLog(
            user_id=current_user.id,
            tool_name=tool_name,
            action=f"Failed to execute {tool_name}",
            input_params=json.dumps(tool_input),
            result=str(e)[:500],
            status="error",
            device_id=current_user.device_id
        )
        db.add(log_entry)
        db.commit()
        
        return {
            "success": False,
            "tool": tool_name,
            "error": str(e)
        }


@app.post("/api/execute-tool", response_model=ToolResult)
async def execute_tool_endpoint_legacy(
    request: Request,
    tool_input: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy alias for older clients: /api/execute-tool -> /api/tools/execute"""
    return await execute_tool_endpoint(
        request=request,
        tool_input=tool_input,
        current_user=current_user,
        db=db,
    )


@app.post("/api/chat", response_model=ToolResult)
async def chat_endpoint_legacy(
    request: Request,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy chat alias: maps /api/chat payloads to ask_copilot tool execution."""
    data = data or {}
    query = str(data.get("query", "") or data.get("prompt", "") or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query or prompt is required")

    tool_input = {"tool": "ask_copilot", "query": query}
    model = str(data.get("model", "") or "").strip()
    if model:
        tool_input["model"] = model

    return await execute_tool_endpoint(
        request=request,
        tool_input=tool_input,
        current_user=current_user,
        db=db,
    )


@app.post("/api/copilot/chat", response_model=ToolResult)
async def copilot_chat_endpoint_legacy(
    request: Request,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy alias for older clients expecting /api/copilot/chat."""
    return await chat_endpoint_legacy(
        request=request,
        data=data,
        current_user=current_user,
        db=db,
    )

@app.get("/api/agent/notifications")
async def get_agent_notifications(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tasks = db.query(AgentTask).filter(
        AgentTask.user_id == current_user.id,
        AgentTask.notified == False,
        AgentTask.status.in_(["completed", "failed"])
    ).order_by(AgentTask.finished_at.desc()).limit(20).all()

    items = []
    for t in tasks:
        ok = t.status == "completed"
        items.append({
            "task_id": t.id,
            "tool": t.tool_name,
            "agent_session_id": t.agent_session_id,
            "status": t.status,
            "message": (
                f"Task #{t.id} finished successfully"
                if ok else f"Task #{t.id} finished with errors"
            ),
            "crawler_url": _crawler_url_from_request(request, t.id),
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        })
        t.notified = True
    db.commit()
    return {"notifications": items}


@app.get("/api/agent/sessions")
async def list_agent_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_copilot_permission(current_user, db)
    sessions = db.query(AgentSession).filter(
        AgentSession.user_id == current_user.id,
        AgentSession.is_active == True
    ).order_by(AgentSession.updated_at.desc()).limit(100).all()
    out = []
    for s in sessions:
        last_msg = db.query(AgentSessionMessage).filter(
            AgentSessionMessage.session_id == s.id
        ).order_by(AgentSessionMessage.created_at.desc()).first()
        msg_count = db.query(AgentSessionMessage).filter(
            AgentSessionMessage.session_id == s.id
        ).count()
        out.append({
            "id": s.id,
            "name": s.name,
            "agent": s.agent,
            "model": s.model,
            "project_path": s.project_path,
            "allow_tools": s.allow_tools,
            "last_task_id": s.last_task_id,
            "message_count": msg_count,
            "last_message_preview": (last_msg.content[:160] if (last_msg and last_msg.content) else None),
            "last_message_role": (last_msg.role if last_msg else None),
            "last_message_at": (last_msg.created_at.isoformat() if (last_msg and last_msg.created_at) else None),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        })
    return {"sessions": out}


@app.post("/api/agent/sessions")
async def create_agent_session(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_copilot_permission(current_user, db)
    data = data or {}
    agent = (str(data.get("agent", "copilot") or "copilot").strip().lower())
    if agent not in {"copilot", "claude", "codex"}:
        agent = "copilot"
    s = AgentSession(
        user_id=current_user.id,
        name=(str(data.get("name", "") or "").strip() or "agent session"),
        agent=agent,
        model=(str(data.get("model", "") or "").strip() or None),
        project_path=(str(data.get("project_path", "") or "").strip() or None),
        allow_tools=(str(data.get("allow_tools", "all") or "all").strip() or "all"),
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name, "agent": s.agent, "model": s.model, "project_path": s.project_path, "allow_tools": s.allow_tools}


@app.get("/api/agent/sessions/{session_id}")
async def get_agent_session_messages(
    session_id: int,
    limit: int = 40,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_copilot_permission(current_user, db)
    s = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
        AgentSession.is_active == True
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    msgs = db.query(AgentSessionMessage).filter(
        AgentSessionMessage.session_id == s.id
    ).order_by(AgentSessionMessage.created_at.desc()).limit(max(1, min(limit, 200))).all()

    return {
        "session": {
            "id": s.id,
            "name": s.name,
            "agent": s.agent,
            "model": s.model,
            "project_path": s.project_path,
            "allow_tools": s.allow_tools,
            "last_task_id": s.last_task_id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        },
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(msgs)
        ]
    }


@app.post("/api/agent/sessions/{session_id}/send")
async def send_agent_session_message(
    session_id: int,
    data: dict,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_copilot_permission(current_user, db)
    enforce_plan_limits(current_user, db)

    data = data or {}
    prompt = str(data.get("prompt", "") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required")

    continue_raw = data.get("continue_session", True)
    continue_session = continue_raw if isinstance(continue_raw, bool) else str(continue_raw).strip().lower() in {"1", "true", "yes", "on"}
    async_raw = data.get("async", True)
    run_async = async_raw if isinstance(async_raw, bool) else str(async_raw).strip().lower() in {"1", "true", "yes", "on"}

    session = db.query(AgentSession).filter(
        AgentSession.id == session_id,
        AgentSession.user_id == current_user.id,
        AgentSession.is_active == True
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    effective_prompt = _build_session_prompt(db, session.id, prompt) if continue_session else prompt
    db.add(AgentSessionMessage(session_id=session.id, role="user", content=prompt[:8000]))
    session.updated_at = datetime.utcnow()
    db.commit()

    params = {
        "prompt": effective_prompt,
        "agent": (session.agent or "copilot"),
        "project_path": (session.project_path or ""),
        "model": (session.model or ""),
        "allow_tools": (session.allow_tools or "all"),
    }

    # Enforce trust policy/approval for sensitive tool execution.
    policy_row = _get_or_create_trust_policy(current_user.id, db)
    policy = apply_profile_defaults(normalize_policy_row(policy_row))
    allowed, blocked_reason, sensitive, sensitivity_reason = evaluate_request(policy, "ask_agent", params)
    if not allowed:
        blocked_msg_map = {
            "kill_switch_enabled": "Execution blocked: emergency kill switch is enabled.",
            "blocked_destructive_pattern": "Execution blocked by destructive-command protection policy.",
            "network_command_blocked": "Execution blocked: network commands are disabled in your policy.",
            "command_not_in_allowlist": "Execution blocked: command is not in your allowlist.",
        }
        blocked_msg = blocked_msg_map.get(blocked_reason, "Execution blocked by trust policy.")
        return {"success": False, "status": "blocked", "error": blocked_msg}

    # Agent CLIs only exist on the user's Mac — must relay.
    if not _relay.is_connected(current_user.id):
        return {
            "success": False, "status": "error",
            "agent_session_id": session.id,
            "result": "❌ No machine connected. Run `vscars start` on your Mac first.",
        }

    machine_id = data.get("machine_id")

    # Try fast path (≤5s); if still running, queue as background relay task.
    try:
        result_data = await asyncio.wait_for(
            _relay.call_tool(current_user.id, machine_id, "ask_agent", params, timeout=180.0),
            timeout=5.0,
        )
        result = result_data.get("result", "")
        success = result_data.get("success", True)
        db.add(AgentSessionMessage(session_id=session.id, role="assistant", content=str(result)[:12000]))
        session.updated_at = datetime.utcnow()
        db.commit()
        return {"success": success, "status": "completed" if success else "failed",
                "agent_session_id": session.id, "result": result}
    except ConnectionError as e:
        return {"success": False, "status": "error", "agent_session_id": session.id,
                "result": f"❌ Connection error: {e}"}
    except asyncio.TimeoutError:
        pass  # Queue it

    task = AgentTask(
        user_id=current_user.id,
        tool_name="ask_agent",
        input_params=json.dumps(params),
        status="queued",
        created_at=datetime.utcnow(),
        agent_session_id=session.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    threading.Thread(target=_run_relay_agent_task, args=(task.id, current_user.id, machine_id, _MAIN_LOOP), daemon=True).start()

    crawl_url = _crawler_url_from_request(request, task.id)
    return {
        "success": True,
        "status": "queued",
        "task_id": task.id,
        "agent_session_id": session.id,
        "crawler_url": crawl_url,
        "result": (
            f"⏳ Agent task queued: #{task.id}\n"
            f"Your agent is running on your Mac — this usually takes 30-120s.\n"
            f"You will get a notification when it finishes."
        ),
    }

@app.get("/api/tools/conversations")
async def get_conversations(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get conversation history with Copilot/Tools"""
    conversations = db.query(ConversationHistory).filter(
        ConversationHistory.user_id == current_user.id
    ).order_by(ConversationHistory.created_at.desc()).limit(limit).all()
    
    return {
        "total": len(conversations),
        "conversations": [
            {
                "id": conv.id,
                "query": conv.query,
                "response": conv.response,
                "tool": conv.tool_used,
                "status": conv.status,
                "timestamp": conv.created_at.isoformat()
            }
            for conv in conversations
        ]
    }

# ==================== RESET & SETTINGS ====================

@app.delete("/api/history/reset")
async def reset_all_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear all conversation history and command logs for current user"""
    try:
        # Delete conversations
        conv_count = db.query(ConversationHistory).filter(
            ConversationHistory.user_id == current_user.id
        ).delete()
        
        # Delete command logs
        log_count = db.query(CommandLog).filter(
            CommandLog.user_id == current_user.id
        ).delete()
        
        db.commit()
        
        # Clear JARVIS execution log
        try:
            log_file = "/tmp/jarvis_execution.log"
            if os.path.exists(log_file):
                os.remove(log_file)
        except:
            pass
        
        return {
            "success": True,
            "message": f"Reset complete. Cleared {conv_count} conversations and {log_count} log entries.",
            "conversations_deleted": conv_count,
            "logs_deleted": log_count
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}

@app.post("/api/settings/github-token")
async def save_github_token(
    data: dict,
    current_user: User = Depends(get_current_user)
):
    """Save GitHub token for Copilot API access"""
    token = data.get("token", "").strip()
    
    if not token:
        return {"success": False, "error": "Token cannot be empty"}
    
    if len(token) < 20:
        return {"success": False, "error": "Token seems too short. Please paste the full token."}
    
    # Save token to project directory with restricted permissions
    try:
        token_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.github_token')
        with open(token_file, "w") as f:
            f.write(token)
        os.chmod(token_file, 0o600)  # Owner read/write only
        
        return {
            "success": True,
            "message": "GitHub token saved! You can now use Ask Copilot.",
            "token_prefix": token[:8] + "..."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/settings/github-token")
async def check_github_token(current_user: User = Depends(get_current_user)):
    """Check if GitHub token is configured"""
    from app.config import GITHUB_TOKEN
    
    token = GITHUB_TOKEN
    
    # Check runtime file too
    if not token:
        try:
            token_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.github_token')
            with open(token_file, "r") as f:
                token = f.read().strip()
        except:
            pass
    
    if token:
        return {
            "configured": True,
            "token_prefix": token[:8] + "...",
            "source": "env" if GITHUB_TOKEN else "runtime"
        }
    
    return {"configured": False}

# ==================== WORKSPACE SETTINGS ====================

@app.post("/api/settings/workspace")
async def save_workspace(
    data: dict,
    current_user: User = Depends(get_current_user),
):
    """Relay workspace path to user's connected machine (stored in ~/.vscars/workspace.txt on Mac)."""
    path = (data.get("workspace_path") or data.get("path", "")).strip()
    if not path:
        return {"success": False, "error": "Path cannot be empty"}

    if not _relay.is_connected(current_user.id):
        return {"success": False, "error": "No machine connected. Run `vscars start` first, then set your workspace."}

    # Write workspace.txt on the user's Mac via relay
    ws_file = os.path.expanduser("~/.vscars/workspace.txt")
    cmd = f"mkdir -p ~/.vscars && echo {shlex.quote(path)} > ~/.vscars/workspace.txt"
    try:
        result = await _relay.call_tool(current_user.id, None, "run_command", {"command": cmd}, timeout=15.0)
        if not result.get("success", True):
            return {"success": False, "error": result.get("result", "Failed to write workspace")}
    except Exception as e:
        return {"success": False, "error": str(e)}

    # Cache the path server-side for display when machine is offline
    try:
        with open(f"/tmp/vscars_ws_{current_user.id}.txt", "w") as f:
            f.write(path)
    except Exception:
        pass

    return {"success": True, "workspace": path, "message": f"Workspace set to: {path}"}


@app.get("/api/settings/workspace")
async def get_workspace(current_user: User = Depends(get_current_user)):
    """Get current workspace — from machine if connected, otherwise from cached value."""
    if _relay.is_connected(current_user.id):
        try:
            result = await _relay.call_tool(
                current_user.id, None, "get_workspace_info", {}, timeout=10.0
            )
            raw = result.get("result", "")
            for line in raw.splitlines():
                if line.startswith("Workspace:"):
                    ws = line.split(":", 1)[1].strip()
                    try:
                        with open(f"/tmp/vscars_ws_{current_user.id}.txt", "w") as f:
                            f.write(ws)
                    except Exception:
                        pass
                    return {"workspace": ws, "source": "machine", "exists": True}
        except Exception:
            pass

    # Fallback: last cached value
    try:
        with open(f"/tmp/vscars_ws_{current_user.id}.txt") as f:
            ws = f.read().strip()
        if ws:
            return {"workspace": ws, "source": "cached", "exists": None}
    except Exception:
        pass

    return {"workspace": "~", "source": "default", "exists": None}

# ==================== AI PROVIDER SETTINGS ROUTES ====================

@app.get("/api/settings/ai")
async def get_ai_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.database import UserAIConfig
    cfg = db.query(UserAIConfig).filter(UserAIConfig.user_id == current_user.id).first()
    if not cfg:
        return {"configured": False, "provider": None, "model": None, "base_url": None, "has_key": False}
    return {
        "configured": bool(cfg.api_key),
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url,
        "has_key": bool(cfg.api_key),
    }

@app.post("/api/settings/ai")
async def save_ai_settings(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.database import UserAIConfig
    from datetime import datetime as _dt
    cfg = db.query(UserAIConfig).filter(UserAIConfig.user_id == current_user.id).first()
    if not cfg:
        cfg = UserAIConfig(user_id=current_user.id)
        db.add(cfg)
    if "provider" in data:
        cfg.provider = data["provider"]
    if "api_key" in data and data["api_key"]:
        cfg.api_key = data["api_key"]
    if "model" in data:
        cfg.model = data["model"] or None
    if "base_url" in data:
        cfg.base_url = data["base_url"] or None
    cfg.updated_at = _dt.utcnow()
    db.commit()
    return {"success": True, "provider": cfg.provider}

@app.delete("/api/settings/ai")
async def delete_ai_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.database import UserAIConfig
    cfg = db.query(UserAIConfig).filter(UserAIConfig.user_id == current_user.id).first()
    if cfg:
        cfg.api_key = None
        db.commit()
    return {"success": True}

# ==================== TRUST & SAFETY ROUTES ====================

@app.get("/api/trust/policy")
async def get_trust_policy(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    policy_row = _get_or_create_trust_policy(current_user.id, db)
    policy = apply_profile_defaults(normalize_policy_row(policy_row))
    return {"policy": policy}


@app.put("/api/trust/policy")
async def update_trust_policy(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    policy_row = _get_or_create_trust_policy(current_user.id, db)

    incoming = {
        "profile": data.get("profile", policy_row.profile or "balanced"),
        "require_approval": data.get("require_approval", policy_row.require_approval),
        "block_destructive": data.get("block_destructive", policy_row.block_destructive),
        "allow_network": data.get("allow_network", policy_row.allow_network),
        "kill_switch": data.get("kill_switch", policy_row.kill_switch),
        "allowed_command_prefixes": data.get("allowed_command_prefixes", policy_row.allowed_command_prefixes or ""),
    }
    merged = apply_profile_defaults(incoming)

    policy_row.profile = merged["profile"]
    policy_row.require_approval = bool(merged["require_approval"])
    policy_row.block_destructive = bool(merged["block_destructive"])
    policy_row.allow_network = bool(merged["allow_network"])
    policy_row.kill_switch = bool(merged["kill_switch"])
    policy_row.allowed_command_prefixes = merged["allowed_command_prefixes"] or ""
    policy_row.updated_at = datetime.utcnow()
    db.commit()

    return {"success": True, "policy": merged}


@app.get("/api/trust/approvals")
async def list_trust_approvals(
    status_filter: str = "pending",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(ToolApproval)
    if current_user.is_superuser:
        pass
    else:
        q = q.filter(ToolApproval.user_id == current_user.id)

    if status_filter and status_filter != "all":
        q = q.filter(ToolApproval.status == status_filter)

    approvals = q.order_by(ToolApproval.created_at.desc()).limit(100).all()
    return {
        "approvals": [
            {
                "id": a.id,
                "user_id": a.user_id,
                "tool_name": a.tool_name,
                "input_params": json.loads(a.input_params or "{}"),
                "status": a.status,
                "sensitivity_reason": a.sensitivity_reason,
                "approved_by": a.approved_by,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
                "consumed_at": a.consumed_at.isoformat() if a.consumed_at else None,
            }
            for a in approvals
        ]
    }


@app.post("/api/trust/approvals/{approval_id}/approve")
async def approve_trust_request(
    approval_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    approval = db.query(ToolApproval).filter(ToolApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if not current_user.is_superuser and approval.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to approve this request")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {approval.status}")

    approval.status = "approved"
    approval.approved_by = current_user.id
    approval.resolved_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": f"Approval #{approval_id} approved"}


@app.post("/api/trust/approvals/{approval_id}/reject")
async def reject_trust_request(
    approval_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    approval = db.query(ToolApproval).filter(ToolApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if not current_user.is_superuser and approval.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to reject this request")
    if approval.status != "pending":
        raise HTTPException(status_code=400, detail=f"Request already {approval.status}")

    approval.status = "rejected"
    approval.approved_by = current_user.id
    approval.resolved_at = datetime.utcnow()
    db.commit()
    return {"success": True, "message": f"Approval #{approval_id} rejected"}


@app.get("/api/trust/audit")
async def get_trust_audit(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    q = db.query(CommandLog)
    if not current_user.is_superuser:
        q = q.filter(CommandLog.user_id == current_user.id)

    rows = q.order_by(CommandLog.created_at.desc()).limit(max(10, min(limit, 200))).all()
    return {
        "events": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "tool": r.tool_name,
                "action": r.action,
                "status": r.status,
                "result": r.result,
                "device_id": r.device_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }

# ==================== HEALTH && INFO ====================

@app.get("/api/bugs")
async def get_bug_tracker(current_user: User = Depends(get_current_user)):
    """Get all tracked bugs"""
    bug_file = os.path.join(os.path.dirname(__file__), "bug_tracker.json")
    try:
        with open(bug_file, 'r') as f:
            bugs_data = json.load(f)
        return bugs_data
    except FileNotFoundError:
        return {"bugs": [], "next_id": 1}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/bugs/report")
async def report_bug(
    bug_input: dict,
    current_user: User = Depends(get_current_user)
):
    """Report a new bug or flag an existing one as recurring"""
    bug_file = os.path.join(os.path.dirname(__file__), "bug_tracker.json")
    
    try:
        with open(bug_file, 'r') as f:
            bugs_data = json.load(f)
    except:
        bugs_data = {"bugs": [], "next_id": 1}
    
    # Check if referencing existing bug by ID
    existing_bug_id = bug_input.get("bug_id")
    if existing_bug_id:
        for bug in bugs_data["bugs"]:
            if bug["id"] == existing_bug_id:
                bug["occurrences"] = bug.get("occurrences", 1) + 1
                bug["last_reported"] = "2026-03-15"
                bug["status"] = "reopened"
                with open(bug_file, 'w') as f:
                    json.dump(bugs_data, f, indent=4)
                return {"success": True, "message": f"Bug #{existing_bug_id} reopened (occurrence #{bug['occurrences']})", "bug": bug}
        return {"success": False, "error": f"Bug #{existing_bug_id} not found"}
    
    # Create new bug
    new_bug = {
        "id": bugs_data["next_id"],
        "title": bug_input.get("title", "Untitled Bug"),
        "description": bug_input.get("description", ""),
        "status": "open",
        "severity": bug_input.get("severity", "medium"),
        "occurrences": 1,
        "first_reported": "2026-03-15",
        "last_reported": "2026-03-15",
        "fix_details": "",
        "root_cause": "",
        "reported_by": current_user.username
    }
    
    bugs_data["bugs"].append(new_bug)
    bugs_data["next_id"] += 1
    
    with open(bug_file, 'w') as f:
        json.dump(bugs_data, f, indent=4)
    
    return {"success": True, "message": f"Bug #{new_bug['id']} created", "bug": new_bug}

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "app": "VSCARS",
        "version": "1.0.0",
        "public_url": ""
    }

@app.get("/install.sh", include_in_schema=False)
@app.get("/install", include_in_schema=False)
async def install_script():
    path = os.path.join(STATIC_DIR, "install.sh")
    return FileResponse(path, media_type="text/plain", filename="install.sh")

# ==================== WEBSOCKET STREAMING ====================

@app.websocket("/ws/stream")
async def stream_command_ws(
    websocket: WebSocket,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """WebSocket endpoint for real-time command output streaming.
    Authenticates via ?token=<jwt> query param (browser WS API can't set headers)."""
    # Authenticate before accepting
    from app.auth import decode_token, is_token_revoked
    from app.tools import _get_workspace, _resolve_path
    import re as _re

    try:
        if is_token_revoked(token, db):
            await websocket.close(code=4001)
            return
        payload = decode_token(token)
        username = payload.get("sub")
        user = db.query(User).filter(User.username == username, User.is_active == True).first()
        if not user:
            await websocket.close(code=4001)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # Permission check
    if not user.is_superuser:
        perm = db.query(UserPermission).filter(UserPermission.user_id == user.id).first()
        if not perm or not perm.can_run_commands:
            await websocket.send_json({"type": "error", "data": "Permission denied: cannot run commands"})
            await websocket.close(code=4003)
            return

    policy_row = _get_or_create_trust_policy(user.id, db)
    policy = apply_profile_defaults(normalize_policy_row(policy_row))
    if policy.get("kill_switch"):
        await websocket.send_json({"type": "error", "data": "Execution blocked: emergency kill switch is enabled."})
        await websocket.close(code=4003)
        return

    BLOCKED_PATTERNS = [
        r'\brm\s+-rf\s+[/~]', r'\bmkfs\b', r'\bdd\s+if=',
        r':(){ :\|:& };:', r'\b>\/dev\/sd', r'\bsudo\s+rm\b',
        r'\bpasswd\b', r'\buserdel\b|\buseradd\b',
        r'>\s*/etc/passwd', r'>\s*/etc/shadow',
    ]

    # Use relay if user has a machine connected (regardless of superuser status)
    use_relay = _relay.is_connected(user.id)

    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command", "").strip()
            cwd = data.get("cwd") or None

            if not command:
                continue

            # Block dangerous patterns
            blocked = any(_re.search(p, command, _re.IGNORECASE) for p in BLOCKED_PATTERNS)
            if blocked:
                await websocket.send_json({"type": "error", "data": "BLOCKED: Dangerous command pattern."})
                await websocket.send_json({"type": "done", "exit_code": 1})
                continue

            await websocket.send_json({"type": "start", "command": command})

            if use_relay:
                # Forward to the user's CLI agent via relay
                if not _relay.is_connected(user.id):
                    await websocket.send_json({"type": "error", "data": "No machine connected. Run `vscars start` on your laptop first."})
                    await websocket.send_json({"type": "done", "exit_code": 1})
                    continue
                try:
                    params = {"command": command}
                    if cwd:
                        params["cwd"] = cwd
                    result = await _relay.call_tool(user.id, None, "run_command", params, timeout=90.0)
                    output = result.get("result", "")
                    await websocket.send_json({"type": "output", "data": str(output)})
                    await websocket.send_json({"type": "done", "exit_code": 0 if result.get("success") else 1})
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "error", "data": "Machine did not respond in time."})
                    await websocket.send_json({"type": "done", "exit_code": -1})
                except ConnectionError as e:
                    await websocket.send_json({"type": "error", "data": str(e)})
                    await websocket.send_json({"type": "done", "exit_code": 1})
            else:
                # Superuser: run directly on the relay host
                try:
                    resolved_cwd = _resolve_path(cwd) if cwd else _get_workspace()
                except Exception as e:
                    await websocket.send_json({"type": "error", "data": f"Invalid working directory: {str(e)}"})
                    await websocket.send_json({"type": "done", "exit_code": 1})
                    continue

                try:
                    proc = await asyncio.create_subprocess_shell(
                        command,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=resolved_cwd,
                    )
                    async for line in proc.stdout:
                        text = line.decode("utf-8", errors="replace")
                        await websocket.send_json({"type": "output", "data": text})
                    await proc.wait()
                    await websocket.send_json({"type": "done", "exit_code": proc.returncode})
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "error", "data": "Command timed out."})
                    await websocket.send_json({"type": "done", "exit_code": -1})
                except Exception as exc:
                    await websocket.send_json({"type": "error", "data": str(exc)})
                    await websocket.send_json({"type": "done", "exit_code": -1})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass


# ==================== GIT PANEL ROUTES ====================

@app.get("/api/git/status")
async def api_git_status(repo_path: str = None, current_user: User = Depends(get_current_user)):
    return git_status(repo_path)

@app.get("/api/git/diff")
async def api_git_diff(staged: bool = False, repo_path: str = None, current_user: User = Depends(get_current_user)):
    return git_diff(repo_path, staged)

@app.post("/api/git/stage")
async def api_git_stage(data: dict, current_user: User = Depends(get_current_user)):
    files = data.get("files", ["."])
    repo_path = data.get("repo_path")
    return git_stage(files if isinstance(files, list) else [files], repo_path)

@app.post("/api/git/unstage")
async def api_git_unstage(data: dict, current_user: User = Depends(get_current_user)):
    files = data.get("files", ["."])
    repo_path = data.get("repo_path")
    return git_unstage(files if isinstance(files, list) else [files], repo_path)

@app.post("/api/git/commit")
async def api_git_commit(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
    if not perm or not perm.can_run_commands:
        raise HTTPException(status_code=403, detail="Commands permission required")
    message = data.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Commit message required")
    result = git_commit(message, data.get("repo_path"))
    log = CommandLog(user_id=current_user.id, tool_name="git_commit", action=f"git commit -m '{message}'",
                     input_params=json.dumps(data), result=result["output"],
                     status="success" if result["success"] else "error", device_id=current_user.device_id)
    db.add(log); db.commit()
    return result

@app.post("/api/git/push")
async def api_git_push(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
    if not perm or not perm.can_run_commands:
        raise HTTPException(status_code=403, detail="Commands permission required")
    result = git_push(data.get("remote", "origin"), data.get("branch", ""), data.get("repo_path"))
    log = CommandLog(user_id=current_user.id, tool_name="git_push", action="git push",
                     input_params=json.dumps(data), result=result["output"],
                     status="success" if result["success"] else "error", device_id=current_user.device_id)
    db.add(log); db.commit()
    return result

@app.get("/api/git/log")
async def api_git_log(n: int = 10, repo_path: str = None, current_user: User = Depends(get_current_user)):
    return git_log(n, repo_path)

@app.get("/api/git/branches")
async def api_git_branches(repo_path: str = None, current_user: User = Depends(get_current_user)):
    return git_branches(repo_path)

@app.post("/api/git/ai-commit-message")
async def api_git_ai_message(data: dict = None, current_user: User = Depends(get_current_user)):
    return git_ai_commit_message((data or {}).get("repo_path"))


# ==================== IDEA VAULT ROUTES ====================

@app.get("/api/ideas")
async def list_ideas(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ideas = db.query(IdeaNote).filter(IdeaNote.user_id == current_user.id).order_by(IdeaNote.created_at.desc()).all()
    return {"ideas": [{"id": i.id, "title": i.title, "body": i.body, "tags": i.tags,
                       "is_done": i.is_done, "created_at": i.created_at.isoformat()} for i in ideas]}

@app.post("/api/ideas")
async def create_idea(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = data or {}

    def _clean_text(value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    body = _clean_text(data.get("body"))
    if not body:
        raise HTTPException(status_code=400, detail="Idea body required")
    title = _clean_text(data.get("title")) or None
    tags = _clean_text(data.get("tags")) or None

    idea = IdeaNote(user_id=current_user.id, title=title, body=body, tags=tags)
    db.add(idea); db.commit(); db.refresh(idea)
    return {"id": idea.id, "title": idea.title, "body": idea.body, "tags": idea.tags,
            "is_done": idea.is_done, "created_at": idea.created_at.isoformat()}

@app.patch("/api/ideas/{idea_id}")
async def update_idea(idea_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = data or {}
    idea = db.query(IdeaNote).filter(IdeaNote.id == idea_id, IdeaNote.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    def _clean_text(value) -> str:
        if value is None:
            return ""
        return str(value).strip()

    if "body" in data:
        new_body = _clean_text(data.get("body"))
        if not new_body:
            raise HTTPException(status_code=400, detail="Idea body required")
        idea.body = new_body
    if "title" in data:
        idea.title = _clean_text(data.get("title")) or None
    if "tags" in data:
        idea.tags = _clean_text(data.get("tags")) or None
    if "is_done" in data: idea.is_done = bool(data["is_done"])
    idea.updated_at = datetime.utcnow()
    db.commit()
    return {"success": True}

@app.delete("/api/ideas/{idea_id}")
async def delete_idea(idea_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    idea = db.query(IdeaNote).filter(IdeaNote.id == idea_id, IdeaNote.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    db.delete(idea); db.commit()
    return {"success": True}


@app.post("/api/ideas/{idea_id}/breakdown")
async def breakdown_idea(
    idea_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Use AI to break an idea into epic → stories → tasks on the scrum board."""
    from app import ai_provider

    if not ai_provider.has_ai_configured(db, current_user.id):
        raise HTTPException(status_code=400, detail="No AI provider configured. Add your API key in Settings → AI Keys.")

    idea = db.query(IdeaNote).filter(IdeaNote.id == idea_id, IdeaNote.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    prompt = f"""You are a senior software architect. Break down this idea into an actionable development plan.

IDEA TITLE: {idea.title or 'Untitled'}
IDEA: {idea.body}

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{{
  "epic": {{
    "title": "Short epic title",
    "description": "What this epic achieves"
  }},
  "stories": [
    {{
      "title": "User story title",
      "description": "As a user, I want...",
      "tasks": [
        {{"title": "Specific technical task", "description": "Implementation detail", "points": 2}},
        {{"title": "Another task", "description": "Detail", "points": 1}}
      ]
    }}
  ]
}}

Keep it practical: 2-4 stories, 2-5 tasks per story. Tasks should be specific enough for an AI agent to implement."""

    try:
        response = ai_provider.chat(
            db, current_user.id,
            [{"role": "user", "content": prompt}],
            system="You are a software architect. Return only valid JSON, no markdown fences."
        )
        import json as _json
        # Strip markdown fences if present
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean
            clean = clean.rsplit("```", 1)[0]
        plan = _json.loads(clean)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI breakdown failed: {e}")

    # Create epic
    epic = ScrumItem(
        user_id=current_user.id,
        item_type="epic",
        title=plan["epic"]["title"],
        description=plan["epic"].get("description", ""),
        status="todo",
        priority="high",
        tags=f"idea:{idea_id}",
    )
    db.add(epic)
    db.flush()

    created_stories = []
    for s in plan.get("stories", []):
        story = ScrumItem(
            user_id=current_user.id,
            item_type="story",
            title=s["title"],
            description=s.get("description", ""),
            status="todo",
            priority="medium",
            parent_id=epic.id,
            tags=f"idea:{idea_id}",
        )
        db.add(story)
        db.flush()

        task_ids = []
        for t in s.get("tasks", []):
            task = ScrumItem(
                user_id=current_user.id,
                item_type="task",
                title=t["title"],
                description=t.get("description", ""),
                status="todo",
                priority="medium",
                parent_id=story.id,
                story_points=t.get("points", 1),
                tags=f"idea:{idea_id}",
            )
            db.add(task)
            db.flush()
            task_ids.append(task.id)

        created_stories.append({"story_id": story.id, "task_ids": task_ids})

    # Mark idea as in progress
    idea.tags = (idea.tags or "") + f",epic:{epic.id}"
    idea.updated_at = datetime.utcnow()
    db.commit()

    return {
        "success": True,
        "epic_id": epic.id,
        "stories": created_stories,
        "message": f"Created 1 epic, {len(plan.get('stories', []))} stories on the scrum board."
    }


async def _run_pipeline_task(user_id: int, session_id: int, story_id: int, db_ref):
    """Run the next pending task in a story pipeline using AI."""
    from app import ai_provider
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        tasks = db.query(ScrumItem).filter(
            ScrumItem.parent_id == story_id,
            ScrumItem.user_id == user_id,
            ScrumItem.status == "todo"
        ).order_by(ScrumItem.id).all()

        for task in tasks:
            task.status = "in_progress"
            task.updated_at = datetime.utcnow()
            db.commit()

            # Build message history for context
            history = db.query(AgentSessionMessage).filter(
                AgentSessionMessage.session_id == session_id,
                AgentSessionMessage.role != "system"
            ).order_by(AgentSessionMessage.created_at).limit(20).all()

            messages = [{"role": m.role, "content": m.content} for m in history]
            messages.append({"role": "user", "content": f"Task: {task.title}\n\n{task.description or ''}\n\nProvide implementation."})

            try:
                response = ai_provider.chat(db, user_id, messages)

                # Save to session
                user_msg = AgentSessionMessage(session_id=session_id, role="user", content=f"Task: {task.title}\n{task.description or ''}")
                ai_msg = AgentSessionMessage(session_id=session_id, role="assistant", content=response)
                db.add(user_msg)
                db.add(ai_msg)

                task.status = "review"
                task.updated_at = datetime.utcnow()

                # Create notification
                notif = AgentTask(
                    user_id=user_id,
                    tool_name="pipeline_task",
                    input_params=f'{{"task": "{task.title[:80]}"}}',
                    status="completed",
                    result=response[:500],
                    agent_session_id=session_id,
                    scrum_item_id=task.id,
                    notified=False,
                )
                db.add(notif)
                db.commit()

                await asyncio.sleep(1)  # brief pause between tasks

            except Exception as e:
                task.status = "todo"
                task.updated_at = datetime.utcnow()
                db.commit()
                break

        # Check if all tasks done → mark story done
        remaining = db.query(ScrumItem).filter(
            ScrumItem.parent_id == story_id,
            ScrumItem.status.in_(["todo", "in_progress"])
        ).count()

        if remaining == 0:
            story = db.query(ScrumItem).filter(ScrumItem.id == story_id).first()
            if story:
                story.status = "done"
                story.updated_at = datetime.utcnow()
                db.commit()
    finally:
        db.close()


@app.post("/api/scrum/items/{item_id}/run")
async def run_scrum_item(
    item_id: int,
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start an AI agent session to work on a scrum story and its tasks."""
    from app import ai_provider

    if not ai_provider.has_ai_configured(db, current_user.id):
        raise HTTPException(status_code=400, detail="No AI provider configured.")

    story = db.query(ScrumItem).filter(
        ScrumItem.id == item_id,
        ScrumItem.user_id == current_user.id
    ).first()
    if not story:
        raise HTTPException(status_code=404, detail="Item not found")

    # Get tasks for this story
    tasks = db.query(ScrumItem).filter(
        ScrumItem.parent_id == item_id,
        ScrumItem.user_id == current_user.id,
        ScrumItem.status.in_(["todo", "in_progress"])
    ).order_by(ScrumItem.id).all()

    if not tasks:
        raise HTTPException(status_code=400, detail="No pending tasks found for this story.")

    # Create or resume agent session for this story
    session = db.query(AgentSession).filter(
        AgentSession.user_id == current_user.id,
        AgentSession.name == f"Pipeline: {story.title[:40]}",
        AgentSession.is_active == True
    ).first()

    if not session:
        session = AgentSession(
            user_id=current_user.id,
            name=f"Pipeline: {story.title[:40]}",
            agent="ai_provider",
            is_active=True,
        )
        db.add(session)
        db.flush()

        # Add system context message
        sys_msg = AgentSessionMessage(
            session_id=session.id,
            role="system",
            content=f"You are working on: {story.title}\n\n{story.description or ''}\n\nYou will be given tasks one by one. For each task, provide a clear implementation plan or code."
        )
        db.add(sys_msg)

    story.status = "in_progress"
    story.updated_at = datetime.utcnow()
    db.commit()

    # Kick off first pending task in background
    asyncio.ensure_future(_run_pipeline_task(current_user.id, session.id, item_id, db))

    return {"success": True, "session_id": session.id, "story": story.title, "pending_tasks": len(tasks)}


# ==================== CLI API KEY ROUTES ====================

@app.get("/api/auth/api-key")
async def get_api_key_status(request: Request, db: Session = Depends(get_db)):
    """Returns key status and plan.
    Accepts Bearer JWT (web UI) or X-VSCARS-Key header (CLI validation during init)."""
    vscars_key = request.headers.get("X-VSCARS-Key", "").strip()
    if vscars_key:
        current_user = _resolve_user_from_api_key(vscars_key, db)
    else:
        from app.auth import decode_token, is_token_revoked
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        token = auth_header.split(" ")[1]
        if is_token_revoked(token, db):
            raise HTTPException(status_code=401, detail="Token revoked")
        payload = decode_token(token)
        current_user = db.query(User).filter(
            User.username == payload.get("sub"), User.is_active == True
        ).first()
        if not current_user:
            raise HTTPException(status_code=401, detail="User not found")

    return {
        "has_key": bool(current_user.api_key_hash),
        "plan": current_user.plan,
        "can_use_machine": True,  # all registered users can connect their machine
    }


@app.post("/api/auth/api-key/generate")
async def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Issue or regenerate the CLI API key. Returns the raw key — shown once.
    Available to all registered users."""
    from app.billing.plan_limits import issue_api_key
    raw_key = issue_api_key(current_user, db)
    return {
        "api_key": raw_key,
        "note": "Save this key — it will not be shown again. Use it with `vscars init`.",
    }


# ==================== SESSION MANAGEMENT ROUTES ====================

@app.get("/api/auth/sessions")
async def list_sessions(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = db.query(UserSession).filter(
        UserSession.user_id == current_user.id, UserSession.is_active == True
    ).order_by(UserSession.last_seen_at.desc()).all()
    return {"sessions": [{"id": s.id, "device_info": s.device_info, "ip_address": s.ip_address,
                          "created_at": s.created_at.isoformat(), "last_seen_at": s.last_seen_at.isoformat()} for s in sessions]}

@app.delete("/api/auth/sessions/{session_id}")
async def revoke_session(session_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = db.query(UserSession).filter(UserSession.id == session_id, UserSession.user_id == current_user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_active = False
    db.commit()
    return {"success": True}


# ==================== MORNING BRIEF / STATS ROUTE ====================

@app.get("/api/dashboard/brief")
async def dashboard_brief(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Returns quick stats for the Morning Brief dashboard widget."""
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())

    commands_today = db.query(CommandLog).filter(
        CommandLog.user_id == current_user.id,
        CommandLog.created_at >= today_start
    ).count()

    # Ideas not yet broken down (no "epic:" in tags)
    all_ideas = db.query(IdeaNote).filter(
        IdeaNote.user_id == current_user.id,
        IdeaNote.is_done == False
    ).all()
    pending_ideas = sum(1 for i in all_ideas if not i.tags or "epic:" not in (i.tags or ""))

    # Stories currently being worked on
    active_pipelines = db.query(ScrumItem).filter(
        ScrumItem.user_id == current_user.id,
        ScrumItem.item_type == "story",
        ScrumItem.status == "in_progress",
    ).count()

    # Tasks waiting for human review
    tasks_in_review = db.query(ScrumItem).filter(
        ScrumItem.user_id == current_user.id,
        ScrumItem.item_type == "task",
        ScrumItem.status == "review",
    ).count()

    return {
        "commands_today": commands_today,
        "pending_ideas": pending_ideas,
        "active_pipelines": active_pipelines,
        "tasks_in_review": tasks_in_review,
        "plan": current_user.plan,
        "daily_api_calls": current_user.daily_api_calls,
    }


# ==================== DEBUG DASHBOARD ====================

@app.get("/api/debug/relay")
async def debug_relay(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Live relay state — connected machines, pending calls, recent tool history."""
    machines = db.query(RegisteredMachine).filter(
        RegisteredMachine.user_id == current_user.id,
        RegisteredMachine.is_active == True,
    ).all()
    connected_ids = set(_relay.get_connected_machines(current_user.id))

    recent_logs = db.query(CommandLog).filter(
        CommandLog.user_id == current_user.id,
    ).order_by(CommandLog.created_at.desc()).limit(20).all()

    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "plan": current_user.plan,
            "is_superuser": current_user.is_superuser,
        },
        "relay": {
            "any_connected": bool(connected_ids),
            "connected_machine_ids": list(connected_ids),
            "pending_calls": list(_relay._pending.keys()),
        },
        "machines": [
            {
                "machine_id": m.machine_id,
                "name": m.name,
                "hostname": m.hostname,
                "os_info": m.os_info,
                "is_connected": m.machine_id in connected_ids,
                "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
            }
            for m in machines
        ],
        "recent_tool_calls": [
            {
                "tool": log.tool_name,
                "action": log.action,
                "status": log.status,
                "result_preview": (log.result or "")[:120],
                "at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in recent_logs
        ],
    }


# ==================== MACHINE REGISTRY & RELAY ====================

def _resolve_user_from_api_key(api_key: str, db: Session) -> User:
    """Look up a user by their raw CLI API key. Raises 401 if invalid."""
    key_hash = _hashlib.sha256(api_key.encode()).hexdigest()
    user = db.query(User).filter(User.api_key_hash == key_hash, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return user


@app.post("/api/machines/register")
async def register_machine(
    request: Request,
    data: dict,
    db: Session = Depends(get_db),
):
    """Register a machine. Called by `vscars init`.
    Accepts either:
      - `Authorization: Bearer <jwt>` (web UI flow)
      - `X-VSCARS-Key: <api_key>` (CLI flow — no login needed)
    Requires Pro plan or above."""
    import secrets as _sec

    # Resolve user from API key header or JWT
    vscars_key = request.headers.get("X-VSCARS-Key", "").strip()
    if vscars_key:
        current_user = _resolve_user_from_api_key(vscars_key, db)
    else:
        # Fall back to JWT auth
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Authentication required (Bearer token or X-VSCARS-Key)")
        from app.auth import decode_token, is_token_revoked
        token = auth_header.split(" ")[1]
        if is_token_revoked(token, db):
            raise HTTPException(status_code=401, detail="Token revoked")
        payload = decode_token(token)
        username = payload.get("sub")
        current_user = db.query(User).filter(User.username == username, User.is_active == True).first()
        if not current_user:
            raise HTTPException(status_code=401, detail="User not found")

    machine_id = (data.get("machine_id") or "").strip()
    name = (data.get("name") or "My Machine").strip()[:64]
    hostname = (data.get("hostname") or "").strip()[:128]
    os_info = (data.get("os_info") or "").strip()[:128]

    if not machine_id:
        raise HTTPException(status_code=400, detail="machine_id required")

    token = _sec.token_urlsafe(32)
    token_hash = _hashlib.sha256(token.encode()).hexdigest()

    existing = db.query(RegisteredMachine).filter(
        RegisteredMachine.machine_id == machine_id
    ).first()

    if existing:
        if existing.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Machine already registered to another user")
        existing.token_hash = token_hash
        existing.name = name
        existing.hostname = hostname
        existing.os_info = os_info
        existing.is_active = True
        db.commit()
    else:
        machine = RegisteredMachine(
            user_id=current_user.id,
            machine_id=machine_id,
            name=name,
            hostname=hostname,
            os_info=os_info,
            token_hash=token_hash,
        )
        db.add(machine)
        db.commit()

    return {"machine_id": machine_id, "token": token, "name": name}


@app.get("/api/machines")
async def list_machines(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the current user's registered machines and their connection status."""
    machines = db.query(RegisteredMachine).filter(
        RegisteredMachine.user_id == current_user.id,
        RegisteredMachine.is_active == True,
    ).all()
    connected_ids = set(_relay.get_connected_machines(current_user.id))
    return {
        "machines": [
            {
                "machine_id": m.machine_id,
                "name": m.name,
                "hostname": m.hostname,
                "os_info": m.os_info,
                "is_connected": m.machine_id in connected_ids,
                "last_seen_at": m.last_seen_at.isoformat() if m.last_seen_at else None,
                "created_at": m.created_at.isoformat(),
            }
            for m in machines
        ],
        "any_connected": bool(connected_ids),
    }


@app.post("/api/machines/autodetect")
async def machine_autodetect(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Called by the CLI agent on connect — stores autodetected workspace, git repos, agents."""
    machine_id = data.get("machine_id")
    if not machine_id:
        raise HTTPException(status_code=400, detail="machine_id required")
    machine = db.query(RegisteredMachine).filter(
        RegisteredMachine.machine_id == machine_id,
        RegisteredMachine.user_id == current_user.id,
        RegisteredMachine.is_active == True,
    ).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    # Store autodetect payload as JSON in os_info extended field
    machine.os_info = data.get("os_info", machine.os_info)
    if data.get("autodetect"):
        import json as _json
        machine.hostname = data.get("hostname", machine.hostname)
        try:
            machine.autodetect = _json.dumps(data.get("autodetect", {}))
        except Exception:
            pass
        # Cache workspace server-side so ask_agent can resolve project_path
        # even before the user explicitly sets it via the app.
        workspace = data.get("autodetect", {}).get("workspace", "")
        if workspace:
            try:
                with open(f"/tmp/vscars_ws_{current_user.id}.txt", "w") as _f:
                    _f.write(workspace)
            except Exception:
                pass
    db.commit()
    return {"success": True}


@app.get("/api/machines/autodetect")
async def get_machine_autodetect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return autodetect data for the user's connected machine."""
    machines = db.query(RegisteredMachine).filter(
        RegisteredMachine.user_id == current_user.id,
        RegisteredMachine.is_active == True,
        RegisteredMachine.is_connected == True,
    ).all()
    result = []
    for m in machines:
        ad = {}
        try:
            import json as _json
            if hasattr(m, "autodetect") and m.autodetect:
                ad = _json.loads(m.autodetect)
        except Exception:
            pass
        result.append({
            "machine_id": m.machine_id,
            "name": m.name,
            "autodetect": ad,
        })
    return {"machines": result}


@app.delete("/api/machines/{machine_id}")
async def delete_machine(
    machine_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    machine = db.query(RegisteredMachine).filter(
        RegisteredMachine.machine_id == machine_id,
        RegisteredMachine.user_id == current_user.id,
    ).first()
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    machine.is_active = False
    db.commit()
    return {"success": True}


@app.websocket("/ws/agent/{machine_token}")
async def agent_websocket(
    ws: WebSocket,
    machine_token: str,
    db: Session = Depends(get_db),
):
    """Persistent WebSocket connection from the vscars CLI agent running on the user's machine.
    The server relays tool calls to this socket and forwards results back to HTTP callers."""
    token_hash = _hashlib.sha256(machine_token.encode()).hexdigest()
    machine = db.query(RegisteredMachine).filter(
        RegisteredMachine.token_hash == token_hash,
        RegisteredMachine.is_active == True,
    ).first()

    if not machine:
        await ws.close(code=4001, reason="Invalid or expired machine token")
        return

    await ws.accept()

    machine.is_connected = True
    machine.last_seen_at = datetime.utcnow()
    db.commit()

    _relay.register(machine.user_id, machine.machine_id, ws)

    try:
        # Send welcome so CLI knows it's connected
        await ws.send_json({
            "type": "connected",
            "machine_id": machine.machine_id,
            "name": machine.name,
        })

        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")

            if msg_type == "tool_result":
                _relay.resolve_call(data.get("call_id", ""), data)

            elif msg_type == "ping":
                machine.last_seen_at = datetime.utcnow()
                db.commit()
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _relay.unregister(machine.user_id, machine.machine_id)
        machine.is_connected = False
        db.commit()


# ==================== COPILOT MODELS ROUTE ====================

# Model catalogue — ordered cheapest → most capable within each tier
# agents: which agent CLIs support this model (copilot=gh copilot, claude=claude CLI, codex=openai codex)
_ALL_MODELS = [
    {"id": "claude-haiku-4.5",      "label": "Claude Haiku 4.5",      "speed": "Fast",    "tier": "standard", "agents": ["copilot", "claude"]},
    {"id": "claude-sonnet-4.6",     "label": "Claude Sonnet 4.6",     "speed": "Balanced", "tier": "standard", "agents": ["copilot", "claude"]},
    {"id": "gpt-4.1",               "label": "GPT-4.1",               "speed": "Balanced", "tier": "standard", "agents": ["copilot", "codex"]},
    {"id": "gpt-5-mini",            "label": "GPT-5 Mini",            "speed": "Fast",    "tier": "standard", "agents": ["copilot", "codex"]},
    {"id": "gpt-5.2",               "label": "GPT-5.2",               "speed": "Smart",   "tier": "premium",  "agents": ["copilot", "codex"]},
    {"id": "gpt-5.4",               "label": "GPT-5.4",               "speed": "Smart",   "tier": "premium",  "agents": ["copilot", "codex"]},
    {"id": "gpt-5.3-codex",         "label": "GPT-5.3 Codex",         "speed": "Smart",   "tier": "premium",  "agents": ["codex"]},
    {"id": "claude-opus-4.6",       "label": "Claude Opus 4.6",       "speed": "Powerful", "tier": "premium",  "agents": ["copilot", "claude"]},
    {"id": "claude-opus-4.6-fast",  "label": "Claude Opus 4.6 Fast",  "speed": "Powerful", "tier": "premium",  "agents": ["claude"]},
    {"id": "gemini-3-pro-preview",  "label": "Gemini 3 Pro",          "speed": "Smart",   "tier": "premium",  "agents": ["copilot"]},
]

_PLAN_MODEL_IDS = {
    # Beta: standard model selection for all users
    "beta": {"claude-haiku-4.5", "claude-sonnet-4.6", "gpt-4.1", "gpt-5-mini", "gpt-5.2"},
}

@app.get("/api/copilot/models")
async def get_copilot_models(current_user: User = Depends(get_current_user)):
    """Return Copilot models available for the user's current plan."""
    plan = current_user.plan
    # Superusers always get every model
    if current_user.is_superuser:
        allowed = {m["id"] for m in _ALL_MODELS}
    else:
        allowed = _PLAN_MODEL_IDS.get(plan, set())

    if not allowed:
        return {"plan": plan, "models": [], "default": None,
                "message": "No models available for your plan."}

    models = [m for m in _ALL_MODELS if m["id"] in allowed]
    return {"plan": plan, "models": models, "default": models[0]["id"]}


# ==================== SCRUM DASHBOARD ROUTES ====================

@app.get("/api/scrum/items")
async def list_scrum_items(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(ScrumItem).filter(
        ScrumItem.user_id == current_user.id
    ).order_by(ScrumItem.updated_at.desc(), ScrumItem.created_at.desc()).all()
    return {
        "items": [
            {
                "id": item.id,
                "item_type": item.item_type,
                "title": item.title,
                "description": item.description,
                "status": item.status,
                "priority": item.priority,
                "parent_id": item.parent_id,
                "story_points": item.story_points,
                "tags": item.tags,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in items
        ]
    }


@app.post("/api/scrum/items")
async def create_scrum_item(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = data or {}
    item_type = str(data.get("item_type", "task") or "task").strip().lower()
    if item_type not in {"bug", "story", "task"}:
        raise HTTPException(status_code=400, detail="item_type must be bug, story, or task")

    title = str(data.get("title", "") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    status_value = str(data.get("status", "todo") or "todo").strip().lower()
    if status_value not in {"backlog", "todo", "in_progress", "review", "done"}:
        status_value = "todo"

    priority = str(data.get("priority", "medium") or "medium").strip().lower()
    if priority not in {"low", "medium", "high", "critical"}:
        priority = "medium"

    parent_id = data.get("parent_id")
    if parent_id in {"", None}:
        parent_id = None
    else:
        parent_id = int(parent_id)

    story_points = data.get("story_points")
    if story_points in {"", None}:
        story_points = None
    else:
        story_points = int(story_points)

    item = ScrumItem(
        user_id=current_user.id,
        item_type=item_type,
        title=title,
        description=str(data.get("description", "") or "").strip() or None,
        status=status_value,
        priority=priority,
        parent_id=parent_id,
        story_points=story_points,
        tags=str(data.get("tags", "") or "").strip() or None,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "item_type": item.item_type,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "priority": item.priority,
        "parent_id": item.parent_id,
        "story_points": item.story_points,
        "tags": item.tags,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@app.patch("/api/scrum/items/{item_id}")
async def update_scrum_item(item_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(ScrumItem).filter(
        ScrumItem.id == item_id,
        ScrumItem.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scrum item not found")

    data = data or {}
    if "status" in data:
        status_value = str(data.get("status", item.status) or item.status).strip().lower()
        if status_value not in {"backlog", "todo", "in_progress", "review", "done"}:
            raise HTTPException(status_code=400, detail="Invalid status")
        item.status = status_value
    if "title" in data:
        title = str(data.get("title", "") or "").strip()
        if title:
            item.title = title
    if "description" in data:
        item.description = str(data.get("description", "") or "").strip() or None
    if "priority" in data:
        priority = str(data.get("priority", item.priority) or item.priority).strip().lower()
        if priority in {"low", "medium", "high", "critical"}:
            item.priority = priority
    if "tags" in data:
        item.tags = str(data.get("tags", "") or "").strip() or None
    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "item_type": item.item_type,
        "title": item.title,
        "description": item.description,
        "status": item.status,
        "priority": item.priority,
        "parent_id": item.parent_id,
        "story_points": item.story_points,
        "tags": item.tags,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@app.delete("/api/scrum/items/{item_id}")
async def delete_scrum_item(item_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = db.query(ScrumItem).filter(
        ScrumItem.id == item_id,
        ScrumItem.user_id == current_user.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Scrum item not found")
    db.delete(item)
    db.commit()
    return {"success": True}


@app.get("/api/scrum/runner")
async def get_scrum_runner_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    state = _get_scrum_runner_state(current_user.id)
    pending_count = db.query(ScrumItem).filter(
        ScrumItem.user_id == current_user.id,
        ScrumItem.item_type == "task",
        ScrumItem.status.in_(["backlog", "todo"]),
    ).count()
    current_item = None
    current_task = None
    if state.get("current_scrum_item_id"):
        item = db.query(ScrumItem).filter(
            ScrumItem.id == state["current_scrum_item_id"],
            ScrumItem.user_id == current_user.id,
        ).first()
        if item:
            current_item = {"id": item.id, "title": item.title, "status": item.status}
    if state.get("current_agent_task_id"):
        task = db.query(AgentTask).filter(
            AgentTask.id == state["current_agent_task_id"],
            AgentTask.user_id == current_user.id,
        ).first()
        if task:
            current_task = {"id": task.id, "status": task.status, "scrum_item_id": task.scrum_item_id}
    return {
        "runner": state,
        "pending_task_count": pending_count,
        "current_item": current_item,
        "current_agent_task": current_task,
    }


@app.post("/api/scrum/runner/start")
async def start_scrum_runner(data: dict = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _ensure_copilot_permission(current_user, db)
    payload = data or {}
    state = _get_scrum_runner_state(current_user.id)
    if state.get("running"):
        return {"success": True, "message": "Autonomous mode is already running.", "runner": state}

    target_path = _validate_runner_target(
        str(payload.get("project_path", "") or ""),
        bool(payload.get("allow_self_work", False)),
    )
    config = {
        "project_path": target_path,
        "allow_tools": str(payload.get("allow_tools", "read") or "read").strip() or "read",
        "allow_self_work": bool(payload.get("allow_self_work", False)),
    }
    new_state = _update_scrum_runner_state(
        current_user.id,
        running=True,
        stop_requested=False,
        current_agent_task_id=None,
        current_scrum_item_id=None,
        last_error="",
        completed_count=0,
        started_at=datetime.utcnow().isoformat(),
        config=config,
    )
    threading.Thread(target=_run_scrum_runner, args=(current_user.id,), daemon=True).start()
    return {"success": True, "message": "Autonomous mode started.", "runner": new_state}


@app.post("/api/scrum/runner/stop")
async def stop_scrum_runner(current_user: User = Depends(get_current_user)):
    state = _get_scrum_runner_state(current_user.id)
    if not state.get("running"):
        return {"success": True, "message": "Autonomous mode is already stopped.", "runner": state}
    new_state = _update_scrum_runner_state(current_user.id, stop_requested=True)
    return {"success": True, "message": "Autonomous stop requested.", "runner": new_state}


# ==================== SERVE FRONTEND (must be LAST — catch-all) ====================

@app.get("/", include_in_schema=False)
async def serve_landing():
    landing = os.path.join(STATIC_DIR, "landing.html")
    if os.path.exists(landing):
        return FileResponse(landing, media_type="text/html")
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), media_type="text/html")

@app.get("/app", include_in_schema=False)
async def serve_app():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return JSONResponse({"status": "error", "message": "App not found"}, status_code=404)

@app.get("/setup", include_in_schema=False)
async def serve_setup():
    setup_path = os.path.join(STATIC_DIR, "setup.html")
    if os.path.exists(setup_path):
        return FileResponse(setup_path, media_type="text/html")
    return JSONResponse({"status": "error", "message": "Setup guide not found"}, status_code=404)

@app.get("/{full_path:path}", include_in_schema=False)
async def catch_all(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("static/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return JSONResponse({"error": "Web UI not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)
