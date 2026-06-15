from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_STARTER_PRICE_ID,
    STRIPE_PRO_PRICE_ID,
    APP_BASE_URL,
    PRICE_TO_PLAN,
)
from app.models.base import Subscription, PlanName, PLAN_LIMITS, User, get_db

stripe.api_key = STRIPE_SECRET_KEY

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_TO_PRICE: dict[str, str] = {
    "starter": STRIPE_STARTER_PRICE_ID,
    "pro": STRIPE_PRO_PRICE_ID,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_or_create_stripe_customer(user: User, db: Session) -> str:
    """Return existing Stripe customer ID or create one."""
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer = stripe.Customer.create(email=user.email, metadata={"user_id": user.id})
    user.stripe_customer_id = customer.id
    db.commit()
    return customer.id


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "pro"


@router.post("/checkout")
def create_checkout_session(
    body: CheckoutRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Create a Stripe Checkout session to subscribe to a paid plan."""
    price_id = PLAN_TO_PRICE.get(body.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    customer_id = _get_or_create_stripe_customer(user, db)

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{APP_BASE_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{APP_BASE_URL}/billing/cancel",
        metadata={"user_id": str(user.id), "plan": body.plan},
    )
    return {"checkout_url": session.url}


@router.post("/portal")
def create_portal_session(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """
    Create a Stripe Customer Portal session so the user can manage/cancel
    their subscription without you building a billing UI.
    """
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found. Subscribe first.")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{APP_BASE_URL}/billing/status",
    )
    return {"portal_url": session.url}


@router.get("/status")
def billing_status(
    user: User = Depends(require_user),
):
    """Return the current plan, usage, and limits for the authenticated user."""
    sub = user.subscription
    if not sub:
        return {"plan": "free", "status": "none", "usage": 0, "limit": PLAN_LIMITS[PlanName.free]}

    limit = PLAN_LIMITS[sub.plan]
    return {
        "plan": sub.plan,
        "status": sub.status,
        "usage": sub.usage_count,
        "limit": limit,
        "remaining": max(0, limit - sub.usage_count),
        "period_end": sub.period_end,
    }


@router.get("/success", summary="Stripe checkout success redirect")
def checkout_success(session_id: str, user: User = Depends(require_user)):
    """
    Stripe redirects here after a successful checkout.
    The subscription is activated via the webhook — this endpoint just
    confirms to the client that payment was received.
    """
    return {
        "message": "Payment successful. Your plan will be activated shortly.",
        "session_id": session_id,
    }


@router.get("/cancel", summary="Stripe checkout cancel redirect")
def checkout_cancel():
    """Stripe redirects here when the user closes the checkout without paying."""
    return {"message": "Checkout cancelled. No charges were made."}


# ---------------------------------------------------------------------------
# Stripe webhook  (POST /webhooks/stripe — mounted in main.py)
# ---------------------------------------------------------------------------

async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe events to keep subscription state in sync.

    Stripe sends signed POST requests to this endpoint. Verify the signature
    with STRIPE_WEBHOOK_SECRET to prevent spoofing.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event_type = event["type"]
    data = event["data"]["object"]

    # ------------------------------------------------------------------
    # checkout.session.completed — user just paid for the first time
    # ------------------------------------------------------------------
    if event_type == "checkout.session.completed":
        user_id = int(data["metadata"]["user_id"])
        plan_name = data["metadata"]["plan"]
        stripe_sub_id = data.get("subscription")

        stripe_sub = stripe.Subscription.retrieve(stripe_sub_id)
        period_end = datetime.fromtimestamp(
            stripe_sub["current_period_end"], tz=timezone.utc
        )

        sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
        if sub:
            sub.stripe_subscription_id = stripe_sub_id
            sub.plan = PlanName(plan_name)
            sub.status = "active"
            sub.usage_count = 0  # reset on plan change
            sub.period_start = datetime.now(timezone.utc)
            sub.period_end = period_end
        db.commit()

    # ------------------------------------------------------------------
    # customer.subscription.updated — renewal, upgrade, downgrade
    # ------------------------------------------------------------------
    elif event_type == "customer.subscription.updated":
        stripe_sub_id = data["id"]
        new_status = data["status"]
        period_end = datetime.fromtimestamp(
            data["current_period_end"], tz=timezone.utc
        )
        # Determine plan from price ID
        price_id = data["items"]["data"][0]["price"]["id"]
        plan_name = PRICE_TO_PLAN.get(price_id, "free")

        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == stripe_sub_id)
            .first()
        )
        if sub:
            old_period_end = sub.period_end
            sub.status = new_status
            sub.period_end = period_end
            sub.plan = PlanName(plan_name)
            # Reset usage on renewal (period_end advanced)
            if old_period_end and period_end > old_period_end.replace(tzinfo=timezone.utc):
                sub.usage_count = 0
            db.commit()

    # ------------------------------------------------------------------
    # customer.subscription.deleted — canceled / expired
    # ------------------------------------------------------------------
    elif event_type == "customer.subscription.deleted":
        stripe_sub_id = data["id"]
        sub = (
            db.query(Subscription)
            .filter(Subscription.stripe_subscription_id == stripe_sub_id)
            .first()
        )
        if sub:
            sub.status = "canceled"
            sub.plan = PlanName.free  # downgrade to free on cancel
            sub.stripe_subscription_id = None
            sub.period_end = None
            sub.usage_count = 0
            db.commit()

    # ------------------------------------------------------------------
    # invoice.payment_failed — card declined, grace period starts
    # ------------------------------------------------------------------
    elif event_type == "invoice.payment_failed":
        stripe_sub_id = data.get("subscription")
        if stripe_sub_id:
            sub = (
                db.query(Subscription)
                .filter(Subscription.stripe_subscription_id == stripe_sub_id)
                .first()
            )
            if sub:
                sub.status = "past_due"
                db.commit()

    return {"received": True}
