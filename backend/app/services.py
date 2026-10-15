"""Application services: use cases composed from domain rules and queries."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import queries
from .domain import TransactionKind, allocate_goals, progress_pct, savings_from
from .models import Goal, Transaction, User
from .schemas import (
    GoalIn,
    GoalOut,
    SummaryOut,
    TransactionIn,
    TransactionOut,
    TransactionPage,
)


def _goal_out(goal: Goal, saved_cents: int) -> GoalOut:
    return GoalOut(
        id=goal.id,
        name=goal.name,
        target_cents=goal.target_cents,
        saved_cents=saved_cents,
        progress_pct=progress_pct(saved_cents, goal.target_cents),
    )


def _goal_progress(db: Session, user_id: int) -> list[tuple[Goal, int]]:
    goals = queries.list_goals(db, user_id)
    savings = queries.savings_cents(db, user_id)
    allocations = {a.goal_id: a.saved_cents for a in allocate_goals(goals, savings)}
    return [(goal, allocations.get(goal.id, 0)) for goal in goals]


def create_transaction(body: TransactionIn, db: Session, user: User) -> TransactionOut:
    kind = TransactionKind(body.kind)
    tx = Transaction(
        user_id=user.id,
        kind=kind,
        category=body.category.strip().lower(),
        amount_cents=body.amount_cents,
        roundup_cents=savings_from(body.amount_cents, kind),
        occurred_on=body.occurred_on or date.today(),
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return TransactionOut.model_validate(tx)


def list_transactions(
    period: str, limit: int, offset: int, db: Session, user: User
) -> TransactionPage:
    since = queries.period_start(period)
    rows, total = queries.list_transactions(db, user.id, since=since, limit=limit, offset=offset)
    return TransactionPage(
        items=[TransactionOut.model_validate(t) for t in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def summary(period: str, db: Session, user: User) -> SummaryOut:
    since = queries.period_start(period)
    totals = queries.totals(db, user.id, since=since)
    allocations = allocate_goals(queries.list_goals(db, user.id), totals.roundup_savings_cents)
    return SummaryOut(
        income_cents=totals.income_cents,
        expense_cents=totals.expense_cents,
        balance_cents=totals.balance_cents,
        roundup_savings_cents=totals.roundup_savings_cents,
        unallocated_savings_cents=max(
            0, totals.roundup_savings_cents - sum(a.saved_cents for a in allocations)
        ),
        transaction_count=queries.transaction_count(db, user.id, since=since),
        spending_by_category=[
            {"category": category, "cents": cents}
            for category, cents in queries.spending_by_category(db, user.id, since=since)
        ],
    )


def create_goal(body: GoalIn, db: Session, user: User) -> GoalOut:
    goal = Goal(user_id=user.id, name=body.name.strip(), target_cents=body.target_cents)
    db.add(goal)
    db.commit()
    db.refresh(goal)
    for candidate, saved in _goal_progress(db, user.id):
        if candidate.id == goal.id:
            return _goal_out(candidate, saved)
    return _goal_out(goal, 0)


def list_goals(db: Session, user: User) -> list[GoalOut]:
    return [_goal_out(goal, saved) for goal, saved in _goal_progress(db, user.id)]
