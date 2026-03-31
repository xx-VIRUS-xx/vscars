"""Thin Stripe SDK wrapper. All Stripe calls go through here."""
import os
from typing import Optional

try:
    import stripe as _stripe
    _stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_AVAILABLE = bool(_stripe.api_key)
except ImportError:
    _stripe = None
    STRIPE_AVAILABLE = False

from app.config import (
    APP_BASE_URL,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_PRO_MONTHLY,
    STRIPE_PRICE_TEAM_MONTHLY,
    STRIPE_PRICE_SELF_HOSTED_MONTHLY,
    STRIPE_PRICE_SELF_HOSTED_LIFETIME,
)

PRICE_IDS = {
    "pro": STRIPE_PRICE_PRO_MONTHLY,
    "team": STRIPE_PRICE_TEAM_MONTHLY,
    "self_hosted_monthly": STRIPE_PRICE_SELF_HOSTED_MONTHLY,
    "self_hosted_lifetime": STRIPE_PRICE_SELF_HOSTED_LIFETIME,
}

# Maps Stripe price ID → internal plan name
PRICE_TO_PLAN = {
    STRIPE_PRICE_PRO_MONTHLY: "pro",
    STRIPE_PRICE_TEAM_MONTHLY: "team",
    STRIPE_PRICE_SELF_HOSTED_MONTHLY: "self_hosted",
    STRIPE_PRICE_SELF_HOSTED_LIFETIME: "self_hosted",
}


def _require_stripe():
    if not STRIPE_AVAILABLE:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="Stripe is not configured. Set STRIPE_SECRET_KEY in .env.",
        )
    return _stripe


def create_or_get_customer(email: str, username: str) -> str:
    """Return existing Stripe customer ID or create a new one."""
    stripe = _require_stripe()
    existing = stripe.Customer.list(email=email, limit=1)
    if existing.data:
        return existing.data[0].id
    customer = stripe.Customer.create(
        email=email,
        metadata={"username": username},
    )
    return customer.id


def create_checkout_session(
    customer_id: str,
    price_id: str,
    plan_key: str,
    user_id: int,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> str:
    """Return Stripe Checkout URL."""
    stripe = _require_stripe()
    is_subscription = plan_key not in ("self_hosted_lifetime",)
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription" if is_subscription else "payment",
        success_url=success_url or f"{APP_BASE_URL}/billing?success=1",
        cancel_url=cancel_url or f"{APP_BASE_URL}/billing?cancelled=1",
        metadata={"user_id": str(user_id), "plan_key": plan_key},
    )
    return session.url


def create_portal_session(customer_id: str) -> str:
    """Return Stripe Billing Portal URL."""
    stripe = _require_stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{APP_BASE_URL}/billing",
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str):
    """Validate Stripe webhook signature and return the event."""
    stripe = _require_stripe()
    return stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
