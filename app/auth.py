from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException, Depends
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES
from app.models.base import ApiKey, User, get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

async def require_api_key(
    x_api_key: str = Header(...),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Validate X-API-Key header and return the ApiKey ORM object."""
    record = (
        db.query(ApiKey)
        .filter(ApiKey.key == x_api_key, ApiKey.is_active == True)  # noqa: E712
        .first()
    )
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    return record


async def require_user(
    api_key_record: ApiKey = Depends(require_api_key),
    db: Session = Depends(get_db),
) -> User:
    """Return the User associated with the supplied API key."""
    user = db.query(User).filter(User.id == api_key_record.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
