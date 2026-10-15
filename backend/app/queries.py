"""Read models. Every aggregation lives here so the routers stay thin."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .domain import Totals, TransactionKind
from .models import Goal, Transaction, User


def period_start(period: str, today: date | None = None) -> date | None:
    anchor = today or date.today()
    if period == "month":
        return anchor.replace(day=1)
    if period == "year":
        return anchor.replace(month=1, day=1)
    return None


def _window(stmt: Select[Any], since: date | None) -> Select[Any]:
    return stmt if since is None else stmt.where(Transaction.occurred_on >= since)


def totals(db: Session, user_id: int, *, since: date | None = None) -> Totals:
    """Aggregate debits, income and round-up savings over a period.

    `expense_cents` sums the amount actually debited (amount + round-up) so
    the balance reflects real money movement. `roundup_savings_cents` is the
    share of that debit redirected to savings, not an extra amount.
    """
    debit = func.sum(Transaction.amount_cents + Transaction.roundup_cents)
    income = func.sum(Transaction.amount_cents)
    savings = func.sum(Transaction.roundup_cents)
    row = db.execute(
        _window(
            select(
                func.coalesce(income.filter(Transaction.kind == TransactionKind.INCOME), 0),
                func.coalesce(debit.filter(Transaction.kind == TransactionKind.EXPENSE), 0),
                func.coalesce(savings.filter(Transaction.kind == TransactionKind.EXPENSE), 0),
            ).where(Transaction.user_id == user_id),
            since,
        )
    ).one()
    return Totals(
        income_cents=int(row[0]), expense_cents=int(row[1]), roundup_savings_cents=int(row[2])
    )


def savings_cents(db: Session, user_id: int, *, since: date | None = None) -> int:
    return totals(db, user_id, since=since).roundup_savings_cents


def spending_by_category(
    db: Session, user_id: int, *, since: date | None = None
) -> list[tuple[str, int]]:
    rows = db.execute(
        _window(
            select(Transaction.category, func.sum(Transaction.amount_cents))
            .where(Transaction.user_id == user_id, Transaction.kind == TransactionKind.EXPENSE)
            .group_by(Transaction.category)
            .order_by(func.sum(Transaction.amount_cents).desc()),
            since,
        )
    ).all()
    return [(category, int(cents)) for category, cents in rows]


def transaction_count(db: Session, user_id: int, *, since: date | None = None) -> int:
    return int(
        db.scalar(
            _window(select(func.count(Transaction.id)).where(Transaction.user_id == user_id), since)
        )
        or 0
    )


def list_transactions(
    db: Session, user_id: int, *, since: date | None = None, limit: int, offset: int
) -> tuple[list[Transaction], int]:
    base = _window(select(Transaction).where(Transaction.user_id == user_id), since)
    total = int(
        db.scalar(
            _window(select(func.count(Transaction.id)).where(Transaction.user_id == user_id), since)
        )
        or 0
    )
    rows = db.scalars(
        base.order_by(Transaction.occurred_on.desc(), Transaction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def list_goals(db: Session, user_id: int) -> list[Goal]:
    return list(db.scalars(select(Goal).where(Goal.user_id == user_id).order_by(Goal.id)))


def owned_goal(db: Session, goal_id: int, user_id: int) -> Goal | None:
    goal = db.get(Goal, goal_id)
    return goal if goal and goal.user_id == user_id else None


def owned_transaction(db: Session, tx_id: int, user_id: int) -> Transaction | None:
    tx = db.get(Transaction, tx_id)
    return tx if tx and tx.user_id == user_id else None


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


__all__ = [
    "find_user_by_email",
    "list_goals",
    "list_transactions",
    "owned_goal",
    "owned_transaction",
    "period_start",
    "savings_cents",
    "spending_by_category",
    "totals",
    "transaction_count",
]
