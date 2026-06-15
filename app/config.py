import os
from dotenv import load_dotenv

load_dotenv()

STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_STARTER_PRICE_ID: str = os.getenv("STRIPE_STARTER_PRICE_ID", "")
STRIPE_PRO_PRICE_ID: str = os.getenv("STRIPE_PRO_PRICE_ID", "")
APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
JWT_SECRET: str = os.getenv("JWT_SECRET", "insecure-default-change-me")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days

# Map Stripe price ID → plan name (populated at runtime once env is loaded)
PRICE_TO_PLAN: dict[str, str] = {}
if STRIPE_STARTER_PRICE_ID:
    PRICE_TO_PLAN[STRIPE_STARTER_PRICE_ID] = "starter"
if STRIPE_PRO_PRICE_ID:
    PRICE_TO_PLAN[STRIPE_PRO_PRICE_ID] = "pro"
