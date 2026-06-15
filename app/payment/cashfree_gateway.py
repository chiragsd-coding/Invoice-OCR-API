"""
Cashfree Payments gateway implementation (secondary / fallback).

Uses the Cashfree REST API v2023-08-01 directly via httpx.
Docs: https://docs.cashfree.com/docs/payment-gateway

Flow:
  1. POST /billing/create-order  → returns checkout_url (Cashfree hosted page)
  2. Client redirects user to checkout_url
  3. User pays (UPI / card / netbanking / wallet)
  4. Cashfree POSTs to /webhooks/cashfree
  5. verify_webhook() confirms HMAC-SHA256 + base64 signature
  6. Subscription activated in DB
"""
from __future__ import annotations

import base64
import hashlib
import hmac

import httpx

from app.config import (
    CASHFREE_APP_ID,
    CASHFREE_SECRET_KEY,
    CASHFREE_WEBHOOK_SECRET,
    CASHFREE_ENV,
    APP_BASE_URL,
)
from app.payment.base import (
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentGateway,
    PaymentStatus,
)

_BASE_URLS = {
    "TEST": "https://sandbox.cashfree.com/pg",
    "PROD": "https://api.cashfree.com/pg",
}


class CashfreeGateway(PaymentGateway):

    def __init__(self) -> None:
        if not CASHFREE_APP_ID or not CASHFREE_SECRET_KEY:
            raise RuntimeError("CASHFREE_APP_ID and CASHFREE_SECRET_KEY must be set in .env")
        self._base = _BASE_URLS.get(CASHFREE_ENV.upper(), _BASE_URLS["TEST"])
        self._headers = {
            "x-client-id": CASHFREE_APP_ID,
            "x-client-secret": CASHFREE_SECRET_KEY,
            "x-api-version": "2023-08-01",
            "Content-Type": "application/json",
        }

    def create_order(self, req: CreateOrderRequest) -> CreateOrderResponse:
        """Create a Cashfree order and return the hosted checkout URL."""
        order_id = req.receipt or f"order_{req.user_id}_{req.plan}"
        payload = {
            "order_id": order_id,
            "order_amount": req.amount / 100,   # Cashfree uses rupees, not paise
            "order_currency": req.currency,
            "customer_details": {
                "customer_id": str(req.user_id),
                "customer_email": req.user_email,
                "customer_phone": "9999999999",  # replace with real phone when available
            },
            "order_meta": {
                "return_url": (
                    f"{APP_BASE_URL}/billing/success"
                    f"?order_id={{order_id}}&gateway=cashfree"
                ),
                "notify_url": f"{APP_BASE_URL}/webhooks/cashfree",
            },
            "order_note": f"plan={req.plan} user={req.user_id}",
        }
        resp = httpx.post(f"{self._base}/orders", json=payload, headers=self._headers)
        resp.raise_for_status()
        data = resp.json()

        return CreateOrderResponse(
            order_id=data["order_id"],
            amount=req.amount,
            currency=req.currency,
            gateway="cashfree",
            checkout_url=data.get("payment_link"),
        )

    def fetch_status(self, payment_id: str) -> PaymentStatus:
        """Fetch a Cashfree order by order_id and normalise status."""
        resp = httpx.get(f"{self._base}/orders/{payment_id}", headers=self._headers)
        resp.raise_for_status()
        data = resp.json()

        raw = data.get("order_status", "")
        status = (
            "paid"    if raw == "PAID" else
            "failed"  if raw in ("EXPIRED", "CANCELLED") else
            "pending"
        )
        return PaymentStatus(
            order_id=payment_id,
            payment_id=str(data.get("cf_order_id", "")),
            status=status,
            amount=int(float(data.get("order_amount", 0)) * 100),  # back to paise
            currency=data.get("order_currency", "INR"),
            gateway="cashfree",
        )

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """
        Cashfree signs: timestamp + raw_body with HMAC-SHA256, then base64-encodes.
        The signature is in x-webhook-signature; timestamp in x-webhook-timestamp.
        """
        if not CASHFREE_WEBHOOK_SECRET:
            return True  # skip in dev when secret not configured

        received = headers.get("x-webhook-signature", "")
        timestamp = headers.get("x-webhook-timestamp", "")
        message = timestamp.encode() + raw_body
        expected = base64.b64encode(
            hmac.new(
                CASHFREE_WEBHOOK_SECRET.encode(),
                message,
                hashlib.sha256,
            ).digest()
        ).decode()
        return hmac.compare_digest(expected, received)
