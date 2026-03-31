from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from app.database import init_db, get_db, User, UserPermission, AccessRequest, CommandLog, ConversationHistory, PasswordResetToken, IdeaNote, SavedWorkflow, UserSession
from app.git_ops import git_status, git_diff, git_stage, git_unstage, git_commit, git_push, git_log, git_branches, git_ai_commit_message
import hashlib as _hashlib
from app.schemas import (
    UserRegister, UserLogin, Token, UserResponse, PermissionResponse,
    AccessRequestCreate, AccessRequestResponse, ToolInput, ToolResult
)
from app.auth import (
    hash_password, verify_password, create_access_token,
    get_current_user, get_superuser, check_permission
)
from app.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES, SUPERUSER_PHONE, STATIC_DIR,
    MAX_REQUEST_SIZE, RATE_LIMIT_LOGIN, RATE_LIMIT_API
)
from app.tools import execute_tool, TOOLS, _reset_allowed_roots
from app.utils.qr_code import create_qr_auth_token
from app.utils.ngrok_helper import NgrokManager
from app.billing.routes import billing_router
from app.email import send_welcome, send_password_reset
from app.billing.plan_limits import apply_plan_to_permissions, enforce_plan_limits
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
import json
import re

# Initialize database
init_db()

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
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info"""
    return current_user

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
    
    # Execute tool
    try:
        params = {k: v for k, v in tool_input.items() if k != "tool" and v is not None}
        result = execute_tool(tool_name, **params)
        
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
            "result": result
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
    ngrok_url = NgrokManager.get_public_url()
    
    return {
        "status": "ok",
        "app": "VS Code Copilot Mobile Controller",
        "version": "1.0.0",
        "ngrok_enabled": NgrokManager.is_active(),
        "public_url": ngrok_url
    }

@app.get("/api/ngrok/url")
async def get_ngrok_url(current_user: User = Depends(get_superuser)):
    """Get ngrok public URL (superuser only)"""
    url = NgrokManager.get_public_url()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ngrok tunnel not active"
        )
    
    return {"public_url": url}

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
            cwd = data.get("cwd") or _get_workspace()

            if not command:
                continue

            # Block dangerous patterns
            blocked = any(_re.search(p, command, _re.IGNORECASE) for p in BLOCKED_PATTERNS)
            if blocked:
                await websocket.send_json({"type": "error", "data": "BLOCKED: Dangerous command pattern."})
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
    body = data.get("body", "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Idea body required")
    idea = IdeaNote(user_id=current_user.id, title=data.get("title", "").strip() or None,
                    body=body, tags=data.get("tags", "").strip() or None)
    db.add(idea); db.commit(); db.refresh(idea)
    return {"id": idea.id, "title": idea.title, "body": idea.body, "tags": idea.tags,
            "is_done": idea.is_done, "created_at": idea.created_at.isoformat()}

@app.patch("/api/ideas/{idea_id}")
async def update_idea(idea_id: int, data: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    idea = db.query(IdeaNote).filter(IdeaNote.id == idea_id, IdeaNote.user_id == current_user.id).first()
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")
    if "body" in data: idea.body = data["body"]
    if "title" in data: idea.title = data["title"] or None
    if "tags" in data: idea.tags = data["tags"] or None
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
    "free":        [],  # copilot disabled
    "pro":         {"claude-haiku-4.5", "claude-sonnet-4.6", "gpt-4.1", "gpt-5-mini", "gpt-5.2"},
    "team":        {m["id"] for m in _ALL_MODELS},  # all
    "self_hosted": {m["id"] for m in _ALL_MODELS},  # all
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
    
    # Start ngrok if enabled
    if True:  # Change to check env var
        NgrokManager.start_tunnel(PORT)
    
    uvicorn.run(app, host=HOST, port=PORT)
