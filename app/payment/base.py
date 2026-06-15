"""
Abstract payment gateway interface.

All providers (Stripe, Razorpay, Cashfree) implement PaymentGateway.
Billing routes import only this module — never a gateway SDK directly.
Switch providers by changing ACTIVE_GATEWAY in .env.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CreateOrderRequest:
    user_id: int
    user_email: str
    plan: str               # "starter" | "pro"
    amount: int             # in paise (₹1 = 100)
    currency: str = "INR"
    receipt: str | None = None


@dataclass
class CreateOrderResponse:
    """Everything the client needs to launch the payment UI."""
    order_id: str           # gateway order / session ID
    amount: int             # in paise
    currency: str
    gateway: str            # "stripe" | "razorpay" | "cashfree"
    # Razorpay: pass key_id + order_id to Checkout.js
    key_id: str | None = None
    # Stripe / Cashfree: redirect user to this URL
    checkout_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaymentStatus:
    order_id: str
    payment_id: str | None
    status: str             # "paid" | "pending" | "failed"
    amount: int
    currency: str
    gateway: str


class PaymentGateway(ABC):

    @abstractmethod
    def create_order(self, req: CreateOrderRequest) -> CreateOrderResponse:
        """Create a payment order / session and return checkout details."""

    @abstractmethod
    def fetch_status(self, payment_id: str) -> PaymentStatus:
        """Return current status of a payment by its gateway payment ID."""

    @abstractmethod
    def verify_webhook(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """
        Verify the webhook request is genuinely from the gateway.
        Returns True if the signature is valid.
        """
