"""
Razorpay gateway implementation.

Flow:
  1. POST /billing/create-order  → returns order_id + key_id
  2. Client opens Razorpay Checkout.js widget with order_id + key_id
  3. User pays (card / UPI / netbanking / wallet)
  4. Razorpay POSTs to /webhooks/razorpay
  5. verify_webhook() confirms HMAC-SHA256 signature
  6. Subscription activated in DB

Test credentials (sandbox):
  Card  : 4111 1111 1111 1111  CVV: 123  Expiry: 12/26
  UPI   : test@razorpay
"""
from __future__ import annotations

import hashlib
import hmac

import razorpay

from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET
from app.payment.base import (
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentGateway,
    PaymentStatus,
)


class RazorpayGateway(PaymentGateway):

    def __init__(self) -> None:
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            raise RuntimeError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in .env")
        self._client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

    def create_order(self, req: CreateOrderRequest) -> CreateOrderResponse:
        """
        Create a Razorpay order.
        The client uses order_id + key_id with the Checkout.js SDK to collect payment.
        """
        order = self._client.order.create(data={
            "amount": req.amount,           # paise  (₹499 = 49900)
            "currency": req.currency,
            "receipt": req.receipt or f"rcpt_{req.user_id}_{req.plan}",
            "notes": {
                "user_id": str(req.user_id),
                "plan": req.plan,
                "email": req.user_email,
            },
        })
        return CreateOrderResponse(
            order_id=order["id"],
            amount=order["amount"],
            currency=order["currency"],
            gateway="razorpay",
            key_id=RAZORPAY_KEY_ID,         # frontend needs this to init Checkout.js
        )

    def fetch_status(self, payment_id: str) -> PaymentStatus:
        """Fetch a Razorpay payment by pay_xxx ID and normalise status."""
        payment = self._client.payment.fetch(payment_id)
        raw = payment.get("status", "")
        status = (
            "paid"    if raw in ("captured", "authorized") else
            "failed"  if raw == "failed" else
            "pending"
        )
        return PaymentStatus(
            order_id=payment.get("order_id", ""),
            payment_id=payment_id,
            status=status,
            amount=payment.get("amount", 0),
            currency=payment.get("currency", "INR"),
            gateway="razorpay",
        )

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """
        Razorpay signs the raw body with HMAC-SHA256 using your webhook secret.
        The digest is in the X-Razorpay-Signature header.
        """
        if not RAZORPAY_WEBHOOK_SECRET:
            # Webhook secret not configured — skip verification in dev
            return True

        received = headers.get("x-razorpay-signature", "")
        expected = hmac.new(
            RAZORPAY_WEBHOOK_SECRET.encode(),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, received)
