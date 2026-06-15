from fastapi import FastAPI

from app.routes.api import router as ocr_router
from app.routes.auth import router as auth_router
from app.routes.billing import (
    router as billing_router,
    webhook_stripe,
    webhook_razorpay,
    webhook_cashfree,
)

app = FastAPI(
    title="Invoice OCR API",
    description=(
        "OCR-powered invoice extraction with subscription billing.\n\n"
        "Supported payment gateways: **Stripe**, **Razorpay**, **Cashfree**.\n"
        "Switch with `ACTIVE_GATEWAY` in `.env`."
    ),
    version="3.0.0",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(ocr_router)
app.include_router(auth_router)
app.include_router(billing_router)

# Webhook routes are registered outside their router so FastAPI does NOT
# parse the body as JSON before the handler reads the raw bytes.
# Signature verification requires the exact raw body the gateway signed.
app.add_api_route(
    "/webhooks/stripe",
    webhook_stripe,
    methods=["POST"],
    tags=["webhooks"],
    summary="Stripe webhook receiver",
)
app.add_api_route(
    "/webhooks/razorpay",
    webhook_razorpay,
    methods=["POST"],
    tags=["webhooks"],
    summary="Razorpay webhook receiver",
)
app.add_api_route(
    "/webhooks/cashfree",
    webhook_cashfree,
    methods=["POST"],
    tags=["webhooks"],
    summary="Cashfree webhook receiver",
)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/", tags=["health"])
def root():
    return {"status": "ok", "docs": "/docs"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "healthy"}
