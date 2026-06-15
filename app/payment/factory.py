"""
Gateway factory.

Call get_gateway() to get the active provider instance.
Change ACTIVE_GATEWAY in .env to switch — no other code changes needed.

Supported values: "stripe" | "razorpay" | "cashfree"
"""
from __future__ import annotations

from functools import lru_cache

from app.config import ACTIVE_GATEWAY
from app.payment.base import PaymentGateway


@lru_cache(maxsize=1)
def get_gateway() -> PaymentGateway:
    """Return a cached singleton of the active payment gateway."""
    gw = ACTIVE_GATEWAY.lower()

    if gw == "stripe":
        from app.payment.stripe_gateway import StripeGateway
        return StripeGateway()

    if gw == "cashfree":
        from app.payment.cashfree_gateway import CashfreeGateway
        return CashfreeGateway()

    # Default: Razorpay
    from app.payment.razorpay_gateway import RazorpayGateway
    return RazorpayGateway()
