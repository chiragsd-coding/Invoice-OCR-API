import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
JWT_SECRET: str = os.getenv("JWT_SECRET", "insecure-default-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STARTER_PRICE_ID: str = os.getenv("STRIPE_STARTER_PRICE_ID", "")
STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "")

# price_id → plan name  (used in webhook handler)
STRIPE_PRICE_TO_PLAN: dict[str, str] = {}
if STRIPE_STARTER_PRICE_ID:
    STRIPE_PRICE_TO_PLAN[STRIPE_STARTER_PRICE_ID] = "starter"
if STRIPE_PRO_PRICE_ID:
    STRIPE_PRICE_TO_PLAN[STRIPE_PRO_PRICE_ID] = "pro"

# ---------------------------------------------------------------------------
# Razorpay
# ---------------------------------------------------------------------------
RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
RAZORPAY_STARTER_PLAN_ID: str = os.getenv("RAZORPAY_STARTER_PLAN_ID", "")
RAZORPAY_PRO_PLAN_ID: str = os.getenv("RAZORPAY_PRO_PLAN_ID", "")

# ---------------------------------------------------------------------------
# Cashfree
# ---------------------------------------------------------------------------
CASHFREE_APP_ID: str = os.getenv("CASHFREE_APP_ID", "")
CASHFREE_SECRET_KEY: str = os.getenv("CASHFREE_SECRET_KEY", "")
CASHFREE_WEBHOOK_SECRET: str = os.getenv("CASHFREE_WEBHOOK_SECRET", "")
CASHFREE_ENV: str = os.getenv("CASHFREE_ENV", "TEST")   # "TEST" | "PROD"
CASHFREE_STARTER_PLAN_ID: str = os.getenv("CASHFREE_STARTER_PLAN_ID", "")
CASHFREE_PRO_PLAN_ID: str = os.getenv("CASHFREE_PRO_PLAN_ID", "")

# ---------------------------------------------------------------------------
# Active gateway  ("stripe" | "razorpay" | "cashfree")
# ---------------------------------------------------------------------------
ACTIVE_GATEWAY: str = os.getenv("ACTIVE_GATEWAY", "razorpay")

# Convenience maps: plan name → plan/price ID per gateway
RAZORPAY_PLAN_IDS: dict[str, str] = {
    "starter": RAZORPAY_STARTER_PLAN_ID,
    "pro": RAZORPAY_PRO_PLAN_ID,
}
CASHFREE_PLAN_IDS: dict[str, str] = {
    "starter": CASHFREE_STARTER_PLAN_ID,
    "pro": CASHFREE_PRO_PLAN_ID,
}
STRIPE_PLAN_IDS: dict[str, str] = {
    "starter": STRIPE_STARTER_PRICE_ID,
    "pro": STRIPE_PRO_PRICE_ID,
}
