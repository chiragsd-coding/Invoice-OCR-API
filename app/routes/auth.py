import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password, create_access_token, require_user
from app.models.base import User, ApiKey, Subscription, PlanName, PLAN_LIMITS, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new account, generate an API key, and assign the free plan."""
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.flush()  # get user.id before committing

    # Create a persistent API key
    raw_key = secrets.token_hex(32)
    api_key = ApiKey(key=raw_key, user_id=user.id)
    db.add(api_key)

    # Assign free plan subscription
    sub = Subscription(
        user_id=user.id,
        plan=PlanName.free,
        status="active",
        period_start=datetime.now(timezone.utc),
    )
    db.add(sub)
    db.commit()

    token = create_access_token(user.id)
    return {
        "message": "Account created",
        "api_key": raw_key,  # shown once — save it securely
        "token": token,
        "plan": "free",
    }


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT + the user's active API key."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    active_key = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user.id, ApiKey.is_active == True)  # noqa: E712
        .order_by(ApiKey.id.desc())
        .first()
    )

    token = create_access_token(user.id)
    return {
        "token": token,
        "api_key": active_key.key if active_key else None,
        "plan": user.subscription.plan if user.subscription else "free",
    }


@router.get("/me", summary="Get current user profile")
def me(user: User = Depends(require_user)):
    """Return the authenticated user's profile and subscription info."""
    sub = user.subscription
    return {
        "id": user.id,
        "email": user.email,
        "created_at": user.created_at,
        "subscription": {
            "plan": sub.plan if sub else "free",
            "status": sub.status if sub else "none",
            "usage": sub.usage_count if sub else 0,
            "limit": PLAN_LIMITS[sub.plan] if sub else PLAN_LIMITS[PlanName.free],
            "period_end": sub.period_end if sub else None,
        },
    }


@router.post("/api-keys", status_code=201, summary="Generate a new API key")
def create_api_key(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """
    Generate a fresh API key for the authenticated user.
    The key value is only returned once — save it securely.
    """
    raw_key = secrets.token_hex(32)
    api_key = ApiKey(key=raw_key, user_id=user.id)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return {"id": api_key.id, "api_key": raw_key, "created_at": api_key.created_at}


@router.get("/api-keys", summary="List active API keys")
def list_api_keys(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """List all active API keys for the authenticated user (key values are masked)."""
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.user_id == user.id, ApiKey.is_active == True)  # noqa: E712
        .order_by(ApiKey.id.desc())
        .all()
    )
    return [
        {
            "id": k.id,
            "key_preview": k.key[:8] + "..." + k.key[-4:],
            "created_at": k.created_at,
        }
        for k in keys
    ]


@router.delete("/api-keys/{key_id}", status_code=204, summary="Revoke an API key")
def revoke_api_key(
    key_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Deactivate an API key. Requests using this key will be rejected immediately."""
    api_key = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.user_id == user.id, ApiKey.is_active == True)  # noqa: E712
        .first()
    )
    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")
    api_key.is_active = False
    db.commit()
