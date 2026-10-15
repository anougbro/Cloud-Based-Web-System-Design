"""PocketWise business rules.

Pure module: no framework, no session, no I/O. Every rule here is a total
function of its arguments so it can be unit tested without HTTP or a database.

Money model
-----------
All amounts are integer cents. A payment of 12.50 on an expense is *debited*
as 13.00: the 0.50 spare change leaves the spending account and lands in the
round-up savings pool. `roundup_savings_cents` is therefore a *breakdown of*
`expense_cents`, not an additional amount, and the two must never be summed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

CENTS_PER_UNIT = 100
MAX_AMOUNT_CENTS = 100_000_000


class TransactionKind(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


@dataclass(frozen=True, slots=True)
class Totals:
    income_cents: int
    expense_cents: int
    roundup_savings_cents: int

    @property
    def balance_cents(self) -> int:
        return self.income_cents - self.expense_cents


@dataclass(frozen=True, slots=True)
class GoalProgress:
    goal_id: int
    saved_cents: int
    progress_pct: float


class SizableGoal(Protocol):
    id: int
    target_cents: int


def roundup_cents(amount_cents: int) -> int:
    """Spare change needed to reach the next whole currency unit.

    Zero when the amount is already whole, matching the convention used by
    Bank of America and Monzo: a round payment generates no round-up.
    """
    if amount_cents < 0:
        raise ValueError(f"amount_cents must be non-negative, got {amount_cents}")
    return -amount_cents % CENTS_PER_UNIT


def debit_cents(amount_cents: int, kind: TransactionKind) -> int:
    """Total amount leaving the spending account for this transaction."""
    if kind is TransactionKind.EXPENSE:
        return amount_cents + roundup_cents(amount_cents)
    return amount_cents


def savings_from(amount_cents: int, kind: TransactionKind) -> int:
    """Round-up contribution of a single transaction. Income never contributes."""
    if kind is TransactionKind.EXPENSE:
        return roundup_cents(amount_cents)
    return 0


def progress_pct(saved_cents: int, target_cents: int) -> float:
    if target_cents <= 0:
        return 0.0
    return round(min(saved_cents, target_cents) * 100 / target_cents, 1)


def allocate_goals(goals: Iterable[SizableGoal], savings_cents: int) -> list[GoalProgress]:
    """Fill goals in the given order until the savings pool runs dry.

    Order is significant: goals are drained oldest-first. Savings left over
    once every goal is full are returned as `unallocated_savings_cents` by the
    caller rather than silently discarded.
    """
    ordered: Sequence[SizableGoal] = tuple(goals)
    remaining = max(0, savings_cents)
    progress: list[GoalProgress] = []
    for goal in ordered:
        saved = min(remaining, goal.target_cents)
        remaining -= saved
        progress.append(
            GoalProgress(
                goal_id=goal.id,
                saved_cents=saved,
                progress_pct=progress_pct(saved, goal.target_cents),
            )
        )
    return progress


def unallocated_savings(allocations: Sequence[GoalProgress], savings_cents: int) -> int:
    return max(0, savings_cents - sum(a.saved_cents for a in allocations))
