from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from app.database import init_db, get_db, SessionLocal, User, UserPermission, AccessRequest, CommandLog, ConversationHistory, PasswordResetToken, IdeaNote, SavedWorkflow, UserSession, RegisteredMachine, TrustPolicy, ToolApproval, ScrumItem, AgentTask, AgentSession, AgentSessionMessage
from app.git_ops import git_status, git_diff, git_stage, git_unstage, git_commit, git_push, git_log, git_branches, git_ai_commit_message
import hashlib as _hashlib
from app.schemas import (
    UserRegister, UserLogin, Token, UserResponse, PermissionResponse,
    AccessRequestCreate, AccessRequestResponse, ToolInput, ToolResult
)
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_superuser, check_permission, decode_token
)
from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES, SUPERUSER_PHONE, STATIC_DIR,
    MAX_REQUEST_SIZE, RATE_LIMIT_LOGIN, RATE_LIMIT_API, APP_BASE_URL
)
from app.tools import execute_tool, TOOLS, _reset_allowed_roots, _get_workspace
from app import relay as _relay
from app.utils.qr_code import create_qr_auth_token
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
import threading
import time

# Initialize database
init_db()
_SCRUM_RUNNERS = {}
_SCRUM_RUNNER_LOCK = threading.Lock()
_VSCARS_ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Create FastAPI app
app = FastAPI(
    title="VS Code Copilot Mobile Controller",
    description="Control VS Code and Copilot from your mobile device worldwide",
    version="1.0.0"
)

# Rate limit error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Billing router
app.include_router(billing_router)

# CORS — restrict to known origins
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
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
        plan="pro" if is_first_user else "free",
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Set permissions based on plan (first user = pro, others = free)
    apply_plan_to_permissions(new_user, db)

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
        "plan": current_user.plan or "free",
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

# ==================== ACCESS REQUEST ROUTES ====================

@app.post("/api/access/request-via-qr", response_model=AccessRequestResponse)
async def request_access_qr(
    request_data: AccessRequestCreate,
    db: Session = Depends(get_db)
):
    """Create access request with QR code"""
    # Check if user already registered
    existing_user = db.query(User).filter(
        User.device_id == request_data.device_id
    ).first()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device already registered"
        )
    
    # Generate QR code
    qr_image, request_id = create_qr_auth_token(
        request_data.username,
        request_data.email,
        request_data.device_id
    )
    
    # Store request (user doesn't exist yet, so we store username)
    access_request = AccessRequest(
        user_id=0,  # Will be updated when approved
        request_type="qr_code",
        qr_code_data=request_id,
        status="pending"
    )
    
    db.add(access_request)
    db.commit()
    db.refresh(access_request)
    
    return {
        "id": access_request.id,
        "username": request_data.username,
        "request_type": "qr_code",
        "status": "pending",
        "qr_code_data": qr_image,
        "created_at": access_request.created_at
    }

@app.get("/api/access/pending-requests")
async def get_pending_requests(
    current_user: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Get all pending access requests (superuser only)"""
    requests = db.query(AccessRequest).filter(
        AccessRequest.status == "pending"
    ).all()
    
    return {
        "pending_requests": [
            {
                "id": r.id,
                "request_type": r.request_type,
                "qr_code": r.qr_code_data,
                "created_at": r.created_at
            }
            for r in requests
        ]
    }

@app.post("/api/access/approve/{request_id}")
async def approve_request(
    request_id: int,
    current_user: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Approve access request (superuser only)"""
    access_request = db.query(AccessRequest).filter(
        AccessRequest.id == request_id
    ).first()
    
    if not access_request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    access_request.status = "approved"
    db.commit()
    
    return {"message": "Access request approved"}

@app.post("/api/access/reject/{request_id}")
async def reject_request(
    request_id: int,
    current_user: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Reject access request (superuser only)"""
    access_request = db.query(AccessRequest).filter(
        AccessRequest.id == request_id
    ).first()
    
    if not access_request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    access_request.status = "rejected"
    db.commit()
    
    return {"message": "Access request rejected"}

# ==================== PERMISSION ROUTES ====================

@app.get("/api/permissions/{user_id}", response_model=PermissionResponse)
async def get_user_permissions(
    user_id: int,
    current_user: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Get user permissions (superuser only)"""
    permission = db.query(UserPermission).filter(
        UserPermission.user_id == user_id
    ).first()
    
    if not permission:
        raise HTTPException(status_code=404, detail="Permissions not found")
    
    return permission

@app.put("/api/permissions/{user_id}")
async def update_user_permissions(
    user_id: int,
    permissions: PermissionResponse,
    current_user: User = Depends(get_superuser),
    db: Session = Depends(get_db)
):
    """Update user permissions (superuser only)"""
    perm = db.query(UserPermission).filter(
        UserPermission.user_id == user_id
    ).first()
    
    if not perm:
        raise HTTPException(status_code=404, detail="Permissions not found")
    
    perm.can_run_copilot = permissions.can_run_copilot
    perm.can_run_commands = permissions.can_run_commands
    perm.can_edit_files = permissions.can_edit_files
    perm.can_view_files = permissions.can_view_files
    
    db.commit()
    
    return {"message": "Permissions updated"}

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

_ASYNC_AGENT_TOOLS = {"ask_agent", "copilot_agent"}
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
    raw = (project_path or "").strip()
    if not raw:
        return ""
    resolved = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(resolved):
        raise ValueError(f"Directory not found: {resolved}")
    return resolved


def _validate_runner_target(project_path: str, allow_self_work: bool) -> str:
    resolved = _normalize_runner_project_path(project_path)
    if not resolved:
        raise ValueError("Target project path is required for autonomous mode.")
    if not allow_self_work and (resolved == _VSCARS_ROOT or resolved.startswith(_VSCARS_ROOT + os.sep)):
        raise ValueError("Autonomous mode is blocked from working on VSCARS itself unless you enable self-work explicitly.")
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
            threading.Thread(target=_run_agent_task, args=(task.id,), daemon=True).start()
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

    params = {
        k: v for k, v in tool_input.items()
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

    approved_request = None
    if policy.get("require_approval", True) and sensitive:
        fp = request_fingerprint(current_user.id, tool_name, params)
        approved_request = db.query(ToolApproval).filter(
            ToolApproval.user_id == current_user.id,
            ToolApproval.request_fingerprint == fp,
            ToolApproval.status == "approved",
            ToolApproval.consumed_at.is_(None)
        ).order_by(ToolApproval.created_at.desc()).first()

        if not approved_request:
            pending = db.query(ToolApproval).filter(
                ToolApproval.user_id == current_user.id,
                ToolApproval.request_fingerprint == fp,
                ToolApproval.status == "pending"
            ).order_by(ToolApproval.created_at.desc()).first()

            if not pending:
                pending = ToolApproval(
                    user_id=current_user.id,
                    tool_name=tool_name,
                    input_params=json.dumps(params),
                    request_fingerprint=fp,
                    sensitivity_reason=sensitivity_reason,
                    status="pending",
                )
                db.add(pending)
                db.commit()
                db.refresh(pending)

            log_entry = CommandLog(
                user_id=current_user.id,
                tool_name=tool_name,
                action=f"Approval required ({sensitivity_reason})",
                input_params=json.dumps(params),
                result=f"Pending approval #{pending.id}.",
                status="pending_approval",
                device_id=current_user.device_id,
            )
            db.add(log_entry)
            db.commit()
            return {
                "success": False,
                "tool": tool_name,
                "error": f"Approval required before execution. Request #{pending.id} is pending.",
                "approval_required": True,
                "approval_id": pending.id,
            }

        approved_request.status = "consumed"
        approved_request.consumed_at = datetime.utcnow()
        db.commit()

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

        threading.Thread(target=_run_agent_task, args=(task.id,), daemon=True).start()

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

    # Permissions that require the tool to run on the user's own machine
    _MACHINE_PERMS = {"view", "edit", "commands"}

    # Non-superusers must proxy machine-required tools through their CLI agent.
    # Superusers (= the host owner) still run locally as before.
    if not current_user.is_superuser and tool["required_permission"] in _MACHINE_PERMS:
        if not _relay.is_connected(current_user.id):
            raise HTTPException(
                status_code=503,
                detail={
                    "message": (
                        "No machine connected. Install the vscars CLI on your laptop "
                        "and run `vscars start` to connect it."
                    ),
                    "code": "no_machine",
                    "install_cmd": f"curl -fsSL {APP_BASE_URL}/static/install-connector.sh | bash && vscars init",
                    "setup_url": f"{APP_BASE_URL}/setup",
                },
            )
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
        
        # Save conversation history for ask_copilot
        if tool_name == "ask_copilot":
            query = params.get("query", "")
            conversation = ConversationHistory(
                user_id=current_user.id,
                query=query,
                response=result,
                tool_used="ask_copilot",
                status="success" if "COPILOT RESPONSE" in result else "error",
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

@app.get("/api/tools/history")
async def get_command_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get command execution history"""
    logs = db.query(CommandLog).filter(
        CommandLog.user_id == current_user.id
    ).order_by(CommandLog.created_at.desc()).limit(limit).all()
    
    return {
        "total": len(logs),
        "history": [
            {
                "id": log.id,
                "tool": log.tool_name,
                "action": log.action,
                "status": log.status,
                "result": log.result,
                "device": log.device_id,
                "timestamp": log.created_at.isoformat()
            }
            for log in logs
        ]
    }


@app.get("/api/agent/tasks")
async def list_agent_tasks(
    request: Request,
    status_filter: str = "",
    limit: int = 30,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AgentTask).filter(AgentTask.user_id == current_user.id)
    if status_filter:
        q = q.filter(AgentTask.status == status_filter)
    tasks = q.order_by(AgentTask.created_at.desc()).limit(max(1, min(limit, 100))).all()
    return {
        "tasks": [
            {
                "id": t.id,
                "tool": t.tool_name,
                "agent_session_id": t.agent_session_id,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "finished_at": t.finished_at.isoformat() if t.finished_at else None,
                "crawler_url": _crawler_url_from_request(request, t.id),
            }
            for t in tasks
        ]
    }


@app.get("/api/agent/tasks/{task_id}")
async def get_agent_task(
    request: Request,
    task_id: int,
    db: Session = Depends(get_db),
):
    # Graceful auth handling: direct-opened links (no auth header) should not
    # spam 401s; return a safe payload the UI can handle.
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1].strip()
    if not token:
        return {
            "id": task_id,
            "tool": None,
            "agent_session_id": None,
            "status": "auth_required",
            "result": None,
            "error": "Authentication required. Open this from the app session.",
            "created_at": None,
            "started_at": None,
            "finished_at": None,
            "crawler_url": _crawler_url_from_request(request, task_id),
        }

    try:
        payload = decode_token(token)
        username = payload.get("sub")
        current_user = db.query(User).filter(User.username == username, User.is_active == True).first()
    except Exception:
        current_user = None

    if not current_user:
        return {
            "id": task_id,
            "tool": None,
            "agent_session_id": None,
            "status": "auth_required",
            "result": None,
            "error": "Authentication required. Open this from the app session.",
            "created_at": None,
            "started_at": None,
            "finished_at": None,
            "crawler_url": _crawler_url_from_request(request, task_id),
        }

    task = db.query(AgentTask).filter(
        AgentTask.id == task_id,
        AgentTask.user_id == current_user.id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "id": task.id,
        "tool": task.tool_name,
        "agent_session_id": task.agent_session_id,
        "status": task.status,
        "result": task.result,
        "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "crawler_url": _crawler_url_from_request(request, task.id),
    }


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

    if policy.get("require_approval", True) and sensitive:
        fp = request_fingerprint(current_user.id, "ask_agent", params)
        approved = db.query(ToolApproval).filter(
            ToolApproval.user_id == current_user.id,
            ToolApproval.request_fingerprint == fp,
            ToolApproval.status == "approved",
            ToolApproval.consumed_at.is_(None)
        ).order_by(ToolApproval.created_at.desc()).first()
        if not approved:
            pending = db.query(ToolApproval).filter(
                ToolApproval.user_id == current_user.id,
                ToolApproval.request_fingerprint == fp,
                ToolApproval.status == "pending"
            ).order_by(ToolApproval.created_at.desc()).first()
            if not pending:
                pending = ToolApproval(
                    user_id=current_user.id,
                    tool_name="ask_agent",
                    input_params=json.dumps(params),
                    request_fingerprint=fp,
                    sensitivity_reason=sensitivity_reason,
                    status="pending",
                )
                db.add(pending)
                db.commit()
                db.refresh(pending)
            return {
                "success": False,
                "status": "pending_approval",
                "approval_required": True,
                "approval_id": pending.id,
                "error": f"Approval required before execution. Request #{pending.id} is pending.",
            }
        approved.status = "consumed"
        approved.consumed_at = datetime.utcnow()
        db.commit()

    if run_async:
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
        threading.Thread(target=_run_agent_task, args=(task.id,), daemon=True).start()

        crawl_url = _crawler_url_from_request(request, task.id)
        return {
            "success": True,
            "status": "queued",
            "task_id": task.id,
            "agent_session_id": session.id,
            "crawler_url": crawl_url,
            "result": f"⏳ Task queued: #{task.id}",
        }

    result = execute_tool("ask_agent", **params)
    success = not str(result).startswith("❌")
    db.add(AgentSessionMessage(session_id=session.id, role="assistant", content=str(result)[:12000]))
    session.updated_at = datetime.utcnow()
    db.commit()
    return {
        "success": success,
        "status": "completed" if success else "failed",
        "agent_session_id": session.id,
        "result": result,
    }

@app.get("/api/tools/execution-log")
async def get_execution_log(
    lines: int = 100,
    current_user: User = Depends(get_current_user)
):
    """Get backend execution log from JARVIS"""
    log_file = "/tmp/jarvis_execution.log"
    
    # Only superuser can view backend logs
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superuser can view execution logs"
        )
    
    try:
        if not os.path.exists(log_file):
            return {
                "status": "info",
                "message": "No logs available yet",
                "logs": []
            }
        
        with open(log_file, 'r') as f:
            all_lines = f.readlines()
        
        # Get last N lines
        recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        return {
            "status": "success",
            "total_lines": len(all_lines),
            "displayed_lines": len(recent_lines),
            "log_file": log_file,
            "logs": [line.rstrip('\n') for line in recent_lines]
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "logs": []
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
    current_user: User = Depends(get_current_user)
):
    """Save workspace path"""
    path = (data.get("workspace_path") or data.get("path", "")).strip()
    
    if not path:
        return {"success": False, "error": "Path cannot be empty"}
    
    path = os.path.expanduser(path)  # Support ~ notation
    path = os.path.realpath(path)    # Resolve symlinks
    
    if not os.path.isdir(path):
        return {"success": False, "error": f"Directory not found: {path}"}
    
    try:
        with open("/tmp/jarvis_workspace.txt", "w") as f:
            f.write(path)
        # Reset path sandbox cache when workspace changes
        _reset_allowed_roots()
        return {"success": True, "workspace": path, "message": f"Workspace set to: {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/settings/workspace")
async def get_workspace(current_user: User = Depends(get_current_user)):
    """Get current workspace path"""
    from app.config import WORKSPACE_PATH
    
    # Check runtime override
    ws_path = WORKSPACE_PATH
    source = "env"
    try:
        with open("/tmp/jarvis_workspace.txt", "r") as f:
            runtime_path = f.read().strip()
            if runtime_path and os.path.isdir(runtime_path):
                ws_path = runtime_path
                source = "runtime"
    except:
        pass
    
    return {
        "workspace": ws_path or os.path.expanduser("~"),
        "source": source,
        "exists": os.path.isdir(ws_path) if ws_path else True
    }

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
        "app": "VS Code Copilot Mobile Controller",
        "version": "1.0.0",
        "public_url": ""
    }

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

    try:
        while True:
            data = await websocket.receive_json()
            command = data.get("command", "").strip()
            raw_cwd = data.get("cwd") or _get_workspace()

            if not command:
                continue

            try:
                cwd = _resolve_path(raw_cwd)
            except Exception as e:
                await websocket.send_json({"type": "error", "data": f"Invalid working directory: {str(e)}"})
                await websocket.send_json({"type": "done", "exit_code": 1})
                continue

            # Block dangerous patterns
            blocked = any(_re.search(p, command, _re.IGNORECASE) for p in BLOCKED_PATTERNS)
            if blocked:
                await websocket.send_json({"type": "error", "data": "BLOCKED: Dangerous command pattern."})
                await websocket.send_json({"type": "done", "exit_code": 1})
                continue

            # Optional network command restrictions (safe profile)
            if not policy.get("allow_network", True):
                if _re.search(r'\\bcurl\\b|\\bwget\\b|\\bssh\\b|\\bscp\\b|\\bnc\\b|\\bncat\\b|\\brsync\\b', command, _re.IGNORECASE):
                    await websocket.send_json({"type": "error", "data": "BLOCKED: Network commands are disabled in policy."})
                    await websocket.send_json({"type": "done", "exit_code": 1})
                    continue

            await websocket.send_json({"type": "start", "command": command})

            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=cwd,
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


# ==================== SAVED WORKFLOWS ROUTES ====================

@app.get("/api/workflows")
async def list_workflows(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workflows = db.query(SavedWorkflow).filter(SavedWorkflow.user_id == current_user.id).order_by(SavedWorkflow.run_count.desc()).all()
    return {"workflows": [{"id": w.id, "name": w.name, "command": w.command, "cwd": w.cwd,
                           "icon": w.icon, "run_count": w.run_count,
                           "last_run_at": w.last_run_at.isoformat() if w.last_run_at else None} for w in workflows]}

@app.post("/api/workflows")
async def create_workflow(data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    name = data.get("name", "").strip()
    command = data.get("command", "").strip()
    if not name or not command:
        raise HTTPException(status_code=400, detail="Name and command required")
    wf = SavedWorkflow(user_id=current_user.id, name=name, command=command,
                       cwd=data.get("cwd", "").strip() or None, icon=data.get("icon", "⚡"))
    db.add(wf); db.commit(); db.refresh(wf)
    return {"id": wf.id, "name": wf.name, "command": wf.command, "cwd": wf.cwd, "icon": wf.icon}

@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    wf = db.query(SavedWorkflow).filter(SavedWorkflow.id == workflow_id, SavedWorkflow.user_id == current_user.id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    db.delete(wf); db.commit()
    return {"success": True}

@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
    if not perm or not perm.can_run_commands:
        raise HTTPException(status_code=403, detail="Commands permission required")
    wf = db.query(SavedWorkflow).filter(SavedWorkflow.id == workflow_id, SavedWorkflow.user_id == current_user.id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    from app.tools import execute_tool as _exec
    result = _exec("run_command", {"command": wf.command, "cwd": wf.cwd or ""}, current_user.id, current_user.device_id, db)
    wf.run_count += 1
    wf.last_run_at = datetime.utcnow()
    db.commit()
    return result


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
        "can_use_machine": current_user.plan in ("pro", "team", "self_hosted") or current_user.is_superuser,
    }


@app.post("/api/auth/api-key/generate")
async def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Issue or regenerate the CLI API key. Returns the raw key — shown once.
    Requires a paid plan (or superuser)."""
    if not current_user.is_superuser:
        perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
        if not perm or not perm.can_use_machine:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "CLI API keys require a Pro plan or above.",
                    "code": "plan_required",
                    "upgrade_url": "/billing",
                },
            )
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

    ideas_pending = db.query(IdeaNote).filter(
        IdeaNote.user_id == current_user.id,
        IdeaNote.is_done == False
    ).count()

    recent_commits = git_log(5)
    git_stat = git_status()

    return {
        "commands_today": commands_today,
        "ideas_pending": ideas_pending,
        "git_status": git_stat.get("output", ""),
        "recent_commits": recent_commits.get("output", ""),
        "plan": current_user.plan,
        "daily_api_calls": current_user.daily_api_calls,
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

    if not current_user.is_superuser:
        perm = db.query(UserPermission).filter(UserPermission.user_id == current_user.id).first()
        if not perm or not perm.can_use_machine:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": "Machine registration requires a Pro plan or above.",
                    "code": "plan_required",
                    "upgrade_url": "https://vscars.latenightstack.com/#pricing",
                },
            )

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
_ALL_MODELS = [
    {"id": "claude-haiku-4.5",      "label": "Claude Haiku 4.5",      "speed": "Fast",   "tier": "standard"},
    {"id": "claude-sonnet-4.6",     "label": "Claude Sonnet 4.6",     "speed": "Balanced","tier": "standard"},
    {"id": "gpt-4.1",               "label": "GPT-4.1",               "speed": "Balanced","tier": "standard"},
    {"id": "gpt-5-mini",            "label": "GPT-5 Mini",            "speed": "Fast",   "tier": "standard"},
    {"id": "gpt-5.2",               "label": "GPT-5.2",               "speed": "Smart",  "tier": "premium"},
    {"id": "gpt-5.4",               "label": "GPT-5.4",               "speed": "Smart",  "tier": "premium"},
    {"id": "gpt-5.3-codex",         "label": "GPT-5.3 Codex",         "speed": "Smart",  "tier": "premium"},
    {"id": "claude-opus-4.6",       "label": "Claude Opus 4.6",       "speed": "Powerful","tier": "premium"},
    {"id": "claude-opus-4.6-fast",  "label": "Claude Opus 4.6 Fast",  "speed": "Powerful","tier": "premium"},
    {"id": "gemini-3-pro-preview",  "label": "Gemini 3 Pro",          "speed": "Smart",  "tier": "premium"},
]

_PLAN_MODEL_IDS = {
    # Free: limited model selection (AI chat only, no machine access)
    "free":        {"claude-haiku-4.5", "gpt-5-mini"},
    "pro":         {"claude-haiku-4.5", "claude-sonnet-4.6", "gpt-4.1", "gpt-5-mini", "gpt-5.2"},
    "team":        {m["id"] for m in _ALL_MODELS},
    "self_hosted": {m["id"] for m in _ALL_MODELS},
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
                "message": "Copilot is not available on the Free plan. Upgrade to Pro to unlock."}

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
