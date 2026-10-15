from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base
from .domain import TransactionKind

KIND_ENUM = Enum(
    TransactionKind,
    name="transaction_kind",
    values_callable=lambda e: [m.value for m in e],
    native_enum=False,
    create_constraint=True,
    validate_strings=True,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    goals: Mapped[list[Goal]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Transaction(Base):
    """Amounts are integer cents: floating point money is never acceptable."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_transaction_amount_positive"),
        CheckConstraint("roundup_cents >= 0", name="ck_transaction_roundup_non_negative"),
        CheckConstraint(
            "roundup_cents < 100 AND (kind = 'expense' OR roundup_cents = 0)",
            name="ck_transaction_roundup_only_on_expense",
        ),
        Index("ix_transaction_user_recent", "user_id", "occurred_on", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[TransactionKind] = mapped_column(KIND_ENUM)
    category: Mapped[str] = mapped_column(String(50))
    amount_cents: Mapped[int] = mapped_column(Integer)
    roundup_cents: Mapped[int] = mapped_column(Integer, default=0)
    occurred_on: Mapped[date] = mapped_column(Date, index=True)

    user: Mapped[User] = relationship(back_populates="transactions")


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (CheckConstraint("target_cents > 0", name="ck_goal_target_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    target_cents: Mapped[int] = mapped_column(Integer)

    user: Mapped[User] = relationship(back_populates="goals")


class RevokedToken(Base):
    """Logout denylist. Rows expire with the token they invalidate, so the
    table self-prunes once `purge_expired_tokens` runs."""

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
