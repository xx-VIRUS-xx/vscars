"""Billing API routes — mounted at /api/billing"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import LicenseKey, User, get_db
from app.billing.license import key_hash, validate_license_key
from app.billing.plan_limits import PLAN_LIMITS, apply_plan_to_permissions

log = logging.getLogger(__name__)
billing_router = APIRouter(prefix="/api/billing", tags=["billing"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ValidateLicenseRequest(BaseModel):
    license_key: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@billing_router.get("/status")
async def billing_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return current user's plan, usage, and billing flags."""
    limits = PLAN_LIMITS.get(current_user.plan, PLAN_LIMITS["beta"])
    daily_limit = limits["daily_api_calls"]

    # Reset counter if it's a new day (keep status consistent with enforcement)
    today = datetime.utcnow().date()
    reset_date = current_user.daily_reset_at.date() if current_user.daily_reset_at else None
    if reset_date is None or reset_date < today:
        current_user.daily_api_calls = 0
        current_user.daily_reset_at = datetime.utcnow()
        db.commit()

    return {
        "plan": current_user.plan,
        "plan_label": limits["label"],
        "daily_api_calls": current_user.daily_api_calls or 0,
        "daily_limit": daily_limit,
        "trial_ends_at": current_user.trial_ends_at.isoformat() if current_user.trial_ends_at else None,
    }


@billing_router.post("/validate-license")
async def validate_license(
    body: ValidateLicenseRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate a self-hosted license key for the current user."""
    raw_key = body.license_key.strip()

    # Validate HMAC signature + expiry
    try:
        payload = validate_license_key(raw_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Look up key in DB
    hashed = key_hash(raw_key)
    license_record = db.query(LicenseKey).filter(LicenseKey.key_hash == hashed).first()

    if license_record is None:
        raise HTTPException(
            status_code=404,
            detail="License key not found. Make sure you copied it correctly.",
        )

    if not license_record.is_active:
        raise HTTPException(status_code=403, detail="License key has been revoked.")

    if license_record.activation_count >= license_record.max_activations:
        raise HTTPException(
            status_code=403,
            detail=(
                f"License key has reached its activation limit "
                f"({license_record.max_activations}). Contact support."
            ),
        )

    # Activate
    license_record.activation_count += 1
    license_record.last_seen_at = datetime.utcnow()
    current_user.plan = "beta"
    if payload.get("exp"):
        current_user.trial_ends_at = datetime.utcfromtimestamp(payload["exp"])
    db.commit()

    apply_plan_to_permissions(current_user, db)

    return {
        "success": True,
        "plan": "beta",
        "payment_type": payload.get("pt", "one_time"),
        "expires_at": current_user.trial_ends_at.isoformat() if current_user.trial_ends_at else None,
    }
