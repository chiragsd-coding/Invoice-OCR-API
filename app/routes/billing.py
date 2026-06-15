"""
Billing routes — gateway-agnostic.

All payment logic goes through app.payment.factory.get_gateway().
Switch providers by setting ACTIVE_GATEWAY=stripe|razorpay|cashfree in .env.

Endpoints
---------
POST /billing/create-order          Create a payment order (all gateways)
POST /billing/verify                Verify a Razorpay callback after payment
GET  /billing/payment/{payment_id}  Poll payment status
GET  /billing/status                Current plan, usage, limits
GET  /billing/success               Post-payment success landing
GET  /billing/cancel                Post-payment cancel landing

Webhooks (registered separately in main.py for raw body access)
-------
POST /webhooks/stripe
POST /webhooks/razorpay
POST /webhooks/cashfree
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_user
from app.config import (
    APP_BASE_URL,
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_TO_PLAN,
    RAZORPAY_KEY_ID,
    ACTIVE_GATEWAY,
)
from app.models.base import PlanName, PLAN_LIMITS, Subscription, User, get_db
from app.payment import CreateOrderRequest, get_gateway

stripe.api_key = STRIPE_SECRET_KEY

# Plan prices in paise (INR) — update as needed
PLAN_PRICES: dict[str, int] = {
    "starter": 1900_00,   # ₹1,900 / month
    "pro":     4900_00,   # ₹4,900 / month
}

router = APIRouter(prefix="/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _activate_subscription(
    db: Session,
    user_id: int,
    plan: str,
    gateway: str,
    gateway_subscription_id: str,
    period_end: datetime | None = None,
) -> None:
    """Set / upgrade the user's subscription in the DB."""
    sub = db.query(Subscription).filter(Subscription.user_id == user_id).first()
    if not sub:
        return
    sub.gateway = gateway
    sub.gateway_subscription_id = gateway_subscription_id
    sub.plan = PlanName(plan)
    sub.status = "active"
    sub.usage_count = 0
    sub.period_start = datetime.now(timezone.utc)
    sub.period_end = period_end
    db.commit()


# ---------------------------------------------------------------------------
# POST /billing/create-order
# ---------------------------------------------------------------------------

class CreateOrderBody(BaseModel):
    plan: str   # "starter" | "pro"


@router.post("/create-order", summary="Create a payment order")
def create_order(
    body: CreateOrderBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """
    Create a payment order with the active gateway.

    **Razorpay response** — pass `order_id` + `key_id` to Checkout.js on the client:
    ```js
    const rzp = new Razorpay({
        key: data.key_id,
        order_id: data.order_id,
        amount: data.amount,
        currency: data.currency,
        handler: (response) => fetch('/billing/verify', { method:'POST', body: JSON.stringify(response) })
    });
    rzp.open();
    ```

    **Stripe / Cashfree response** — redirect the user to `checkout_url`.
    """
    if body.plan not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {body.plan}")

    gw = get_gateway()
    req = CreateOrderRequest(
        user_id=user.id,
        user_email=user.email,
        plan=body.plan,
        amount=PLAN_PRICES[body.plan],
        receipt=f"rcpt_{user.id}_{uuid.uuid4().hex[:8]}",
    )
    resp = gw.create_order(req)

    return {
        "gateway": resp.gateway,
        "order_id": resp.order_id,
        "amount": resp.amount,
        "currency": resp.currency,
        # Razorpay: use key_id + order_id with Checkout.js
        "key_id": resp.key_id,
        # Stripe / Cashfree: redirect here
        "checkout_url": resp.checkout_url,
    }


# ---------------------------------------------------------------------------
# POST /billing/verify  (Razorpay callback after successful payment)
# ---------------------------------------------------------------------------

class VerifyPaymentBody(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    plan: str


@router.post("/verify", summary="Verify Razorpay payment callback")
def verify_payment(
    body: VerifyPaymentBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """
    Called by the client after Razorpay Checkout.js triggers its `handler`.
    Verifies the payment signature and activates the subscription.
    """
    import hashlib, hmac as _hmac
    from app.config import RAZORPAY_KEY_SECRET

    # Razorpay signature = HMAC-SHA256(order_id + "|" + payment_id, key_secret)
    message = f"{body.razorpay_order_id}|{body.razorpay_payment_id}".encode()
    expected = _hmac.new(
        RAZORPAY_KEY_SECRET.encode(), message, hashlib.sha256
    ).hexdigest()

    if not _hmac.compare_digest(expected, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    _activate_subscription(
        db=db,
        user_id=user.id,
        plan=body.plan,
        gateway="razorpay",
        gateway_subscription_id=body.razorpay_payment_id,
    )
    return {"message": f"Payment verified. {body.plan} plan is now active."}


# ---------------------------------------------------------------------------
# GET /billing/payment/{payment_id}
# ---------------------------------------------------------------------------

@router.get("/payment/{payment_id}", summary="Poll payment status")
def get_payment_status(
    payment_id: str,
    user: User = Depends(require_user),
):
    """Fetch the current status of a payment from the active gateway."""
    gw = get_gateway()
    status = gw.fetch_status(payment_id)
    return {
        "gateway": status.gateway,
        "order_id": status.order_id,
        "payment_id": status.payment_id,
        "status": status.status,
        "amount": status.amount,
        "currency": status.currency,
    }


# ---------------------------------------------------------------------------
# GET /billing/status
# ---------------------------------------------------------------------------

@router.get("/status", summary="Get current plan and usage")
def billing_status(user: User = Depends(require_user)):
    """Return the authenticated user's plan, usage count, and billing period."""
    sub = user.subscription
    if not sub:
        return {
            "plan": "free",
            "status": "active",
            "gateway": None,
            "usage": 0,
            "limit": PLAN_LIMITS[PlanName.free],
            "remaining": PLAN_LIMITS[PlanName.free],
            "period_end": None,
        }
    limit = PLAN_LIMITS[sub.plan]
    return {
        "plan": sub.plan,
        "status": sub.status,
        "gateway": sub.gateway,
        "usage": sub.usage_count,
        "limit": limit,
        "remaining": max(0, limit - sub.usage_count),
        "period_end": sub.period_end,
    }


# ---------------------------------------------------------------------------
# GET /billing/success  and  GET /billing/cancel
# ---------------------------------------------------------------------------

@router.get("/success", summary="Payment success redirect landing")
def payment_success(
    gateway: str = "unknown",
    session_id: str | None = None,
    order_id: str | None = None,
):
    return {
        "message": "Payment received. Your plan will be activated shortly.",
        "gateway": gateway,
        "reference": session_id or order_id,
    }


@router.get("/cancel", summary="Payment cancel redirect landing")
def payment_cancel():
    return {"message": "Payment cancelled. No charges were made."}


# ===========================================================================
# Webhook handlers — mounted in main.py to preserve raw body
# ===========================================================================

async def webhook_stripe(request: Request, db: Session = Depends(get_db)):
    """
    Stripe sends signed events here.
    Events handled: checkout.session.completed, customer.subscription.updated,
                    customer.subscription.deleted, invoice.payment_failed
    """
    raw_body = await request.body()
    headers = dict(request.headers)

    from app.payment.stripe_gateway import StripeGateway
    gw = StripeGateway()
    if not gw.verify_webhook(raw_body, headers):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    event: dict[str, Any] = stripe.Webhook.construct_event(
        raw_body,
        headers.get("stripe-signature", ""),
        STRIPE_WEBHOOK_SECRET,
    )
    etype = event["type"]
    data = event["data"]["object"]

    if etype == "checkout.session.completed":
        user_id = int(data["metadata"]["user_id"])
        plan = data["metadata"]["plan"]
        sub_id = data.get("subscription", "")
        stripe_sub = stripe.Subscription.retrieve(sub_id)
        period_end = datetime.fromtimestamp(
            stripe_sub["current_period_end"], tz=timezone.utc
        )
        _activate_subscription(db, user_id, plan, "stripe", sub_id, period_end)

    elif etype == "customer.subscription.updated":
        sub_id = data["id"]
        new_status = data["status"]
        period_end = datetime.fromtimestamp(data["current_period_end"], tz=timezone.utc)
        price_id = data["items"]["data"][0]["price"]["id"]
        plan = STRIPE_PRICE_TO_PLAN.get(price_id, "free")
        sub = db.query(Subscription).filter(
            Subscription.gateway_subscription_id == sub_id
        ).first()
        if sub:
            old_end = sub.period_end
            sub.status = new_status
            sub.plan = PlanName(plan)
            sub.period_end = period_end
            if old_end and period_end > old_end.replace(tzinfo=timezone.utc):
                sub.usage_count = 0
            db.commit()

    elif etype == "customer.subscription.deleted":
        sub_id = data["id"]
        sub = db.query(Subscription).filter(
            Subscription.gateway_subscription_id == sub_id
        ).first()
        if sub:
            sub.status = "canceled"
            sub.plan = PlanName.free
            sub.gateway_subscription_id = None
            sub.period_end = None
            sub.usage_count = 0
            db.commit()

    elif etype == "invoice.payment_failed":
        sub_id = data.get("subscription")
        if sub_id:
            sub = db.query(Subscription).filter(
                Subscription.gateway_subscription_id == sub_id
            ).first()
            if sub:
                sub.status = "past_due"
                db.commit()

    return {"received": True}


async def webhook_razorpay(request: Request, db: Session = Depends(get_db)):
    """
    Razorpay sends signed events here.
    Events handled: payment.captured, payment.failed, subscription.charged
    """
    raw_body = await request.body()
    headers = dict(request.headers)

    from app.payment.razorpay_gateway import RazorpayGateway
    gw = RazorpayGateway()
    if not gw.verify_webhook(raw_body, headers):
        raise HTTPException(status_code=400, detail="Invalid Razorpay signature")

    import json
    event = json.loads(raw_body)
    etype = event.get("event", "")
    payload = event.get("payload", {})

    if etype == "payment.captured":
        payment = payload.get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        user_id = notes.get("user_id")
        plan = notes.get("plan")
        if user_id and plan:
            _activate_subscription(
                db, int(user_id), plan, "razorpay", payment.get("id", "")
            )

    elif etype == "payment.failed":
        payment = payload.get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        user_id = notes.get("user_id")
        if user_id:
            sub = db.query(Subscription).filter(
                Subscription.user_id == int(user_id)
            ).first()
            if sub:
                sub.status = "past_due"
                db.commit()

    elif etype == "subscription.charged":
        rz_sub = payload.get("subscription", {}).get("entity", {})
        sub = db.query(Subscription).filter(
            Subscription.gateway_subscription_id == rz_sub.get("id")
        ).first()
        if sub:
            sub.status = "active"
            sub.usage_count = 0
            if rz_sub.get("current_end"):
                sub.period_end = datetime.fromtimestamp(
                    rz_sub["current_end"], tz=timezone.utc
                )
            db.commit()

    return {"received": True}


async def webhook_cashfree(request: Request, db: Session = Depends(get_db)):
    """
    Cashfree sends signed events here.
    Events handled: PAYMENT_SUCCESS, PAYMENT_FAILED
    """
    raw_body = await request.body()
    headers = dict(request.headers)

    from app.payment.cashfree_gateway import CashfreeGateway
    gw = CashfreeGateway()
    if not gw.verify_webhook(raw_body, headers):
        raise HTTPException(status_code=400, detail="Invalid Cashfree signature")

    import json
    event = json.loads(raw_body)
    etype = event.get("type", "")
    data = event.get("data", {})

    if etype == "PAYMENT_SUCCESS":
        order = data.get("order", {})
        note: str = order.get("order_note", "")  # "plan=starter user=1"
        parts = dict(p.split("=") for p in note.split() if "=" in p)
        user_id = parts.get("user")
        plan = parts.get("plan")
        if user_id and plan:
            _activate_subscription(
                db, int(user_id), plan, "cashfree",
                order.get("order_id", ""),
            )

    elif etype == "PAYMENT_FAILED":
        order = data.get("order", {})
        note: str = order.get("order_note", "")
        parts = dict(p.split("=") for p in note.split() if "=" in p)
        user_id = parts.get("user")
        if user_id:
            sub = db.query(Subscription).filter(
                Subscription.user_id == int(user_id)
            ).first()
            if sub:
                sub.status = "past_due"
                db.commit()

    return {"received": True}
