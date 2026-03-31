from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session

# ─── Plan definitions ──────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "free": {
        "daily_api_calls": 20,
        "can_run_copilot": False,
        "can_run_commands": False,
        "can_edit_files": False,
        "can_view_files": True,
        "label": "Free",
        "price_monthly": 0,
        "price_lifetime": None,
    },
    "pro": {
        "daily_api_calls": 500,
        "can_run_copilot": True,
        "can_run_commands": True,
        "can_edit_files": True,
        "can_view_files": True,
        "label": "Pro",
        "price_monthly": 9,
        "price_lifetime": None,
    },
    "team": {
        "daily_api_calls": -1,  # unlimited
        "can_run_copilot": True,
        "can_run_commands": True,
        "can_edit_files": True,
        "can_view_files": True,
        "label": "Team",
        "price_monthly": 29,
        "price_lifetime": None,
    },
    "self_hosted": {
        "daily_api_calls": -1,  # unlimited
        "can_run_copilot": True,
        "can_run_commands": True,
        "can_edit_files": True,
        "can_view_files": True,
        "label": "Self-Hosted",
        "price_monthly": 19,
        "price_lifetime": 49,
    },
}


def apply_plan_to_permissions(user, db: Session) -> None:
    """Write UserPermission flags to match user.plan. Call after any plan change."""
    from app.database import UserPermission
    limits = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])

    perm = db.query(UserPermission).filter(UserPermission.user_id == user.id).first()
    if not perm:
        perm = UserPermission(user_id=user.id)
        db.add(perm)

    perm.can_run_copilot = limits["can_run_copilot"]
    perm.can_run_commands = limits["can_run_commands"]
    perm.can_edit_files = limits["can_edit_files"]
    perm.can_view_files = limits["can_view_files"]
    db.commit()


def enforce_plan_limits(user, db: Session) -> None:
    """Enforce daily call limits. Raises HTTP 429 when limit is exceeded.
    Superusers bypass all limits. Call at the top of tool execution."""
    if user.is_superuser:
        return

    # Expire trial if needed
    if (
        user.trial_ends_at
        and user.trial_ends_at < datetime.utcnow()
        and user.plan not in ("free",)
        and not user.stripe_subscription_id
    ):
        user.plan = "free"
        db.commit()
        apply_plan_to_permissions(user, db)

    limits = PLAN_LIMITS.get(user.plan, PLAN_LIMITS["free"])
    daily_limit = limits["daily_api_calls"]

    if daily_limit == -1:
        # Unlimited plan — still track for analytics
        user.daily_api_calls = (user.daily_api_calls or 0) + 1
        db.commit()
        return

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
                    f"Daily limit of {daily_limit} API calls reached for the "
                    f"{limits['label']} plan. Upgrade to unlock more."
                ),
                "plan": user.plan,
                "daily_limit": daily_limit,
                "upgrade_url": "/billing",
            },
        )

    user.daily_api_calls = (user.daily_api_calls or 0) + 1
    db.commit()
