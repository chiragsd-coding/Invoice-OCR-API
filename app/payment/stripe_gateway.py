"""
Stripe gateway implementation.

Flow:
  1. POST /billing/create-order  → returns checkout_url (Stripe Checkout hosted page)
  2. User pays on Stripe-hosted page
  3. Stripe POSTs to /webhooks/stripe
  4. verify_webhook() confirms signature using STRIPE_WEBHOOK_SECRET
  5. Subscription is activated / updated in DB
"""
from __future__ import annotations

import stripe

from app.config import (
    STRIPE_SECRET_KEY,
    STRIPE_WEBHOOK_SECRET,
    APP_BASE_URL,
    STRIPE_PLAN_IDS,
)
from app.payment.base import (
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentGateway,
    PaymentStatus,
)

stripe.api_key = STRIPE_SECRET_KEY


class StripeGateway(PaymentGateway):

    def create_order(self, req: CreateOrderRequest) -> CreateOrderResponse:
        """
        Create a Stripe Checkout Session in subscription mode.
        Returns a hosted checkout_url to redirect the user to.
        """
        price_id = STRIPE_PLAN_IDS.get(req.plan)
        if not price_id:
            raise ValueError(
                f"STRIPE_{req.plan.upper()}_PRICE_ID is not set in .env"
            )

        # Reuse or create Stripe customer
        customers = stripe.Customer.list(email=req.user_email, limit=1)
        if customers.data:
            customer_id = customers.data[0].id
        else:
            customer = stripe.Customer.create(
                email=req.user_email,
                metadata={"user_id": str(req.user_id)},
            )
            customer_id = customer.id

        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url=(
                f"{APP_BASE_URL}/billing/success"
                "?session_id={CHECKOUT_SESSION_ID}&gateway=stripe"
            ),
            cancel_url=f"{APP_BASE_URL}/billing/cancel",
            metadata={"user_id": str(req.user_id), "plan": req.plan},
        )

        return CreateOrderResponse(
            order_id=session.id,
            amount=req.amount,
            currency=req.currency,
            gateway="stripe",
            checkout_url=session.url,
        )

    def fetch_status(self, payment_id: str) -> PaymentStatus:
        """Fetch a Stripe Payment Intent or Checkout Session by ID."""
        # payment_id can be a PaymentIntent (pi_xxx) or Session (cs_xxx)
        if payment_id.startswith("pi_"):
            pi = stripe.PaymentIntent.retrieve(payment_id)
            raw_status = pi.status
            amount = pi.amount
            currency = pi.currency.upper()
            order_id = pi.get("metadata", {}).get("order_id", payment_id)
        else:
            session = stripe.checkout.Session.retrieve(payment_id)
            raw_status = session.payment_status   # "paid" | "unpaid" | "no_payment_required"
            amount = session.amount_total or 0
            currency = (session.currency or "INR").upper()
            order_id = session.id

        status_map = {
            "succeeded": "paid",
            "paid": "paid",
            "requires_payment_method": "failed",
            "canceled": "failed",
            "unpaid": "pending",
        }
        status = status_map.get(raw_status, "pending")

        return PaymentStatus(
            order_id=order_id,
            payment_id=payment_id,
            status=status,
            amount=amount,
            currency=currency,
            gateway="stripe",
        )

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """Verify Stripe webhook signature using the signing secret."""
        sig = headers.get("stripe-signature", "")
        try:
            stripe.Webhook.construct_event(raw_body, sig, STRIPE_WEBHOOK_SECRET)
            return True
        except (stripe.error.SignatureVerificationError, ValueError):
            return False
