from datetime import datetime, timezone

from fastapi import HTTPException, Depends
from sqlalchemy.orm import Session

from app.models.base import Subscription, PlanName, PLAN_LIMITS, User, get_db
from app.auth import require_user


def _reset_if_new_period(sub: Subscription) -> None:
    """Reset usage counter when a new billing period has started."""
    now = datetime.now(timezone.utc)

    # Paid plans: Stripe tells us the period_end; reset when it passes
    if sub.period_end and now > sub.period_end.replace(tzinfo=timezone.utc):
        sub.usage_count = 0
        sub.period_start = now
        # period_end will be updated by the Stripe webhook on renewal
        return

    # Free plan: reset monthly based on period_start
    if sub.plan == PlanName.free and sub.period_start:
        start = sub.period_start.replace(tzinfo=timezone.utc)
        months_elapsed = (now.year - start.year) * 12 + (now.month - start.month)
        if months_elapsed >= 1:
            sub.usage_count = 0
            sub.period_start = now


def check_usage_limit(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> User:
    """
    Enforce plan-based usage limits.

    Raises HTTP 402 when the limit is reached, HTTP 403 when the
    subscription is not active (past_due / canceled).
    Returns the user on success and increments the usage counter.
    """
    sub = user.subscription
    if sub is None:
        raise HTTPException(status_code=403, detail="No active subscription found")

    # Block if subscription is not in a usable state
    if sub.status not in ("active", "trialing"):
        raise HTTPException(
            status_code=402,
            detail=f"Subscription is {sub.status}. Please update your payment method.",
        )

    _reset_if_new_period(sub)

    limit = PLAN_LIMITS[sub.plan]
    if sub.usage_count >= limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Monthly OCR limit of {limit} reached for the {sub.plan} plan. "
                "Upgrade your plan to continue."
            ),
        )

    sub.usage_count += 1
    db.commit()
    return user
