from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session

# ─── Plan definitions ──────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "beta": {
        "label": "Beta",
        "daily_api_calls": 15,
        "can_use_machine": True,
        "can_run_commands": True,
        "can_edit_files": True,
        "can_view_files": True,
        "can_use_ai": True,
        "max_machines": 1,
    }
}


def issue_api_key(user, db: Session) -> str:
    """Generate a new CLI API key for the user, store its hash, return the raw key (shown once)."""
    import secrets
    import hashlib
    raw = "vscars_" + secrets.token_urlsafe(32)
    user.api_key_hash = hashlib.sha256(raw.encode()).hexdigest()
    db.commit()
    return raw


def apply_plan_to_permissions(user, db: Session) -> None:
    """Write UserPermission flags for the user. All users get beta plan limits.
    Also auto-issues a CLI API key if not already present."""
    from app.database import UserPermission
    limits = PLAN_LIMITS["beta"]

    perm = db.query(UserPermission).filter(UserPermission.user_id == user.id).first()
    if not perm:
        perm = UserPermission(user_id=user.id)
        db.add(perm)

    perm.can_run_copilot = True
    perm.can_run_commands = limits["can_run_commands"]
    perm.can_edit_files = limits["can_edit_files"]
    perm.can_view_files = limits["can_view_files"]
    perm.can_use_machine = limits["can_use_machine"]

    # Auto-issue an API key if not already issued
    if not user.api_key_hash:
        issue_api_key(user, db)

    db.commit()


def enforce_plan_limits(user, db: Session) -> None:
    """Enforce daily call limits. Raises HTTP 429 when limit is exceeded.
    Superusers bypass all limits (effective daily_api_calls = 999999)."""
    if user.is_superuser:
        return

    daily_limit = PLAN_LIMITS["beta"]["daily_api_calls"]

    # Reset counter on a new calendar day
    today = datetime.utcnow().date()
    reset_date = user.daily_reset_at.date() if user.daily_reset_at else None
    if reset_date is None or reset_date < today:
        user.daily_api_calls = 0
        user.daily_reset_at = datetime.utcnow()
        db.commit()

    if (user.daily_api_calls or 0) >= daily_limit:
        raise HTTPException(
            status_code=429,
            detail={
                "message": (
                    f"You've used all {daily_limit} beta requests for today. "
                    f"Resets at midnight UTC. Thanks for trying VSCARS!"
                ),
                "plan": "beta",
                "daily_limit": daily_limit,
            },
        )

    user.daily_api_calls = (user.daily_api_calls or 0) + 1
    db.commit()
