from datetime import datetime, timedelta
from typing import Optional
import uuid
import hashlib
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from app.config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
from app.database import User, TokenBlacklist, get_db

# Password hashing - using argon2 instead of bcrypt (no 72-byte limit, more secure)
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hash a password using argon2"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

def _token_hash(token: str) -> str:
    """Create a short hash of a token for blacklist storage"""
    return hashlib.sha256(token.encode()).hexdigest()[:32]

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT token with unique ID for revocation support"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({
        "exp": expire,
        "jti": str(uuid.uuid4())  # Unique token ID for revocation
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    """Decode JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

def revoke_token(token: str, user_id: int, db: Session):
    """Add a token to the blacklist"""
    token_id = _token_hash(token)
    existing = db.query(TokenBlacklist).filter(TokenBlacklist.token_jti == token_id).first()
    if not existing:
        blacklisted = TokenBlacklist(token_jti=token_id, user_id=user_id)
        db.add(blacklisted)
        db.commit()

def is_token_revoked(token: str, db: Session) -> bool:
    """Check if a token has been revoked"""
    token_id = _token_hash(token)
    return db.query(TokenBlacklist).filter(TokenBlacklist.token_jti == token_id).first() is not None

# HTTP Bearer authentication
async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from header or query param (for SSE)"""
    auth_header = request.headers.get("Authorization")
    token = None
    
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        # Fallback: check query param (for EventSource/SSE which can't set headers)
        # WARNING: tokens in query params appear in logs — use sparingly
        token = request.query_params.get("token")
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header"
        )
    
    # Check if token has been revoked (logout)
    if is_token_revoked(token, db):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked"
        )
    
    payload = decode_token(token)
    username: str = payload.get("sub")
    
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive"
        )
    
    return user

async def get_superuser(current_user: User = Depends(get_current_user)) -> User:
    """Ensure user is superuser"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superuser can perform this action"
        )
    return current_user

async def check_permission(
    permission_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> bool:
    """Check if user has specific permission"""
    if current_user.is_superuser:
        return True
    
    from app.database import UserPermission
    
    permission = db.query(UserPermission).filter(
        UserPermission.user_id == current_user.id
    ).first()
    
    if not permission:
        return False
    
    permission_map = {
        "copilot": permission.can_run_copilot,
        "commands": permission.can_run_commands,
        "edit": permission.can_edit_files,
        "view": permission.can_view_files,
    }
    
    return permission_map.get(permission_name, False)
