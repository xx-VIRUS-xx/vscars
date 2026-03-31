"""Billing API routes — mounted at /api/billing"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import LicenseKey, User, get_db
from app.billing.license import generate_license_key, key_hash, validate_license_key
from app.billing.plan_limits import PLAN_LIMITS, apply_plan_to_permissions
from app.billing import stripe_client

log = logging.getLogger(__name__)
billing_router = APIRouter(prefix="/api/billing", tags=["billing"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str  # pro | team | self_hosted_monthly | self_hosted_lifetime


class ValidateLicenseRequest(BaseModel):
    license_key: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _plan_from_checkout_key(plan_key: str) -> str:
    """Map checkout plan key to internal plan name."""
    mapping = {
        "pro": "pro",
        "team": "team",
        "self_hosted_monthly": "self_hosted",
        "self_hosted_lifetime": "self_hosted",
    }
    return mapping.get(plan_key, "free")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@billing_router.get("/status")
async def billing_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return current user's plan, usage, and billing flags."""
    limits = PLAN_LIMITS.get(current_user.plan, PLAN_LIMITS["free"])
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
        "has_stripe_customer": bool(current_user.stripe_customer_id),
        "subscription_active": bool(current_user.stripe_subscription_id),
        "plans": {
            k: {
                "label": v["label"],
                "price_monthly": v["price_monthly"],
                "price_lifetime": v["price_lifetime"],
            }
            for k, v in PLAN_LIMITS.items()
        },
    }


@billing_router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Checkout session and return the redirect URL."""
    plan_key = body.plan
    if plan_key not in stripe_client.PRICE_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {plan_key}")

    price_id = stripe_client.PRICE_IDS.get(plan_key, "")
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Price ID for '{plan_key}' not configured. Set the env var.",
        )

    # Ensure Stripe customer exists
    if not current_user.stripe_customer_id:
        customer_id = stripe_client.create_or_get_customer(
            current_user.email, current_user.username
        )
        current_user.stripe_customer_id = customer_id
        db.commit()

    url = stripe_client.create_checkout_session(
        customer_id=current_user.stripe_customer_id,
        price_id=price_id,
        plan_key=plan_key,
        user_id=current_user.id,
    )
    return {"checkout_url": url}


@billing_router.get("/portal")
async def billing_portal(
    current_user: User = Depends(get_current_user),
):
    """Return Stripe Billing Portal URL to manage subscription."""
    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=400,
            detail="No billing account found. Subscribe to a plan first.",
        )
    url = stripe_client.create_portal_session(current_user.stripe_customer_id)
    return {"portal_url": url}


@billing_router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Stripe webhook events. Must read raw body for signature validation."""
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe_client.construct_webhook_event(raw_body, sig_header)
    except Exception as exc:
        log.warning("Stripe webhook signature failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event["type"]
    data = event["data"]["object"]

    try:
        if event_type == "checkout.session.completed":
            _handle_checkout_completed(data, db)

        elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
            _handle_subscription_updated(data, db)

        elif event_type == "customer.subscription.deleted":
            _handle_subscription_deleted(data, db)

        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(data, db)

    except Exception as exc:
        log.error("Error processing webhook %s: %s", event_type, exc)
        # Still return 200 so Stripe doesn't retry endlessly

    return {"received": True}


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
    current_user.plan = "self_hosted"
    if payload.get("exp"):
        current_user.trial_ends_at = datetime.utcfromtimestamp(payload["exp"])
    db.commit()

    apply_plan_to_permissions(current_user, db)

    return {
        "success": True,
        "plan": "self_hosted",
        "payment_type": payload.get("pt", "one_time"),
        "expires_at": current_user.trial_ends_at.isoformat() if current_user.trial_ends_at else None,
    }


@billing_router.post("/admin/generate-license")
async def admin_generate_license(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Superuser: generate a license key and store it in the DB."""
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Superuser only")

    issued_to = body.get("issued_to", "")
    payment_type = body.get("payment_type", "one_time")
    expires_days = body.get("expires_days")  # None = lifetime

    expires_at = None
    if expires_days:
        import time
        expires_at = int(time.time()) + int(expires_days) * 86400

    raw_key = generate_license_key(
        issued_to=issued_to,
        payment_type=payment_type,
        expires_at=expires_at,
    )
    hashed = key_hash(raw_key)

    record = LicenseKey(
        key_hash=hashed,
        edition="self_hosted",
        issued_to=issued_to,
        payment_type=payment_type,
        max_activations=body.get("max_activations", 3),
        expires_at=datetime.utcfromtimestamp(expires_at) if expires_at else None,
    )
    db.add(record)
    db.commit()

    return {"license_key": raw_key, "issued_to": issued_to, "payment_type": payment_type}


# ─── Webhook handlers ─────────────────────────────────────────────────────────

def _user_by_customer(customer_id: str, db: Session) -> Optional[User]:
    return db.query(User).filter(User.stripe_customer_id == customer_id).first()


def _handle_checkout_completed(session, db: Session):
    customer_id = session.get("customer")
    metadata = session.get("metadata", {})
    plan_key = metadata.get("plan_key", "")
    user_id = int(metadata.get("user_id", 0))

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return

    new_plan = _plan_from_checkout_key(plan_key)

    # For subscriptions, subscription ID will arrive via subscription.updated event.
    # For one-time self-hosted lifetime purchases, activate immediately.
    if plan_key == "self_hosted_lifetime":
        user.plan = "self_hosted"
        user.stripe_subscription_id = None  # not a subscription
        db.commit()
        apply_plan_to_permissions(user, db)
        log.info("Lifetime self-hosted activated for user %s", user_id)
    else:
        # Subscription — wait for subscription.updated event for reliability
        sub_id = session.get("subscription")
        if sub_id:
            user.stripe_subscription_id = sub_id
            user.plan = new_plan
            db.commit()
            apply_plan_to_permissions(user, db)
            log.info("Subscription %s activated plan '%s' for user %s", sub_id, new_plan, user_id)


def _handle_subscription_updated(subscription, db: Session):
    customer_id = subscription.get("customer")
    sub_id = subscription.get("id")
    sub_status = subscription.get("status")  # active, trialing, past_due, canceled

    user = _user_by_customer(customer_id, db)
    if not user:
        return

    # Resolve plan from the first price in the subscription
    items = subscription.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else ""
    new_plan = stripe_client.PRICE_TO_PLAN.get(price_id, user.plan)

    if sub_status in ("active", "trialing"):
        user.plan = new_plan
        user.stripe_subscription_id = sub_id
    elif sub_status in ("past_due",):
        # Give a 7-day grace period
        user.trial_ends_at = datetime.utcnow() + timedelta(days=7)
    elif sub_status in ("canceled", "unpaid"):
        user.plan = "free"
        user.stripe_subscription_id = None

    db.commit()
    apply_plan_to_permissions(user, db)
    log.info("Subscription updated: user %s → plan '%s' (%s)", user.id, user.plan, sub_status)


def _handle_subscription_deleted(subscription, db: Session):
    customer_id = subscription.get("customer")
    user = _user_by_customer(customer_id, db)
    if not user:
        return

    user.plan = "free"
    user.stripe_subscription_id = None
    db.commit()
    apply_plan_to_permissions(user, db)
    log.info("Subscription deleted: user %s downgraded to free", user.id)


def _handle_payment_failed(invoice, db: Session):
    customer_id = invoice.get("customer")
    user = _user_by_customer(customer_id, db)
    if not user:
        return

    # 7-day grace period before downgrade
    user.trial_ends_at = datetime.utcnow() + timedelta(days=7)
    db.commit()
    log.warning("Payment failed for user %s — grace period set", user.id)
