from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    DateTime, Boolean, ForeignKey, Enum
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timezone
import enum

DATABASE_URL = "sqlite:///./ocr.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class PlanName(str, enum.Enum):
    free = "free"
    starter = "starter"
    pro = "pro"


# ---------------------------------------------------------------------------
# Plan limits (OCR calls per billing period)
# ---------------------------------------------------------------------------
PLAN_LIMITS: dict[PlanName, int] = {
    PlanName.free: 50,
    PlanName.starter: 500,
    PlanName.pro: 5000,
}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    stripe_customer_id = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="user", uselist=False, cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="api_keys")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    stripe_subscription_id = Column(String, unique=True, nullable=True)  # None for free plan
    plan = Column(Enum(PlanName), default=PlanName.free, nullable=False)
    status = Column(String, default="active")  # active | past_due | canceled | trialing
    usage_count = Column(Integer, default=0)
    period_start = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    period_end = Column(DateTime, nullable=True)   # None = free plan (monthly reset handled manually)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="subscription")


class OCRResult(Base):
    __tablename__ = "ocr_results"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    text = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # nullable for migration compat
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
