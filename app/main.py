from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from app.routes.api import router as ocr_router
from app.routes.auth import router as auth_router
from app.routes.billing import router as billing_router, stripe_webhook
from app.models.base import get_db

app = FastAPI(
    title="Invoice OCR API",
    description="OCR-powered invoice extraction with Stripe subscription billing.",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(ocr_router)
app.include_router(auth_router)
app.include_router(billing_router)

# Stripe webhook needs the raw request body before any JSON parsing,
# so it is registered as a plain route (not inside the billing router).
app.add_api_route(
    "/webhooks/stripe",
    stripe_webhook,
    methods=["POST"],
    tags=["billing"],
    summary="Stripe webhook receiver",
)


# ---------------------------------------------------------------------------
# Health / root
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"status": "ok", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "healthy"}
