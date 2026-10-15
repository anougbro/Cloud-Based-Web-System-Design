"""Business rules, tested with no database, no session and no HTTP."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain import (
    TransactionKind,
    allocate_goals,
    debit_cents,
    progress_pct,
    roundup_cents,
    savings_from,
    unallocated_savings,
)


@dataclass(frozen=True)
class FakeGoal:
    id: int
    target_cents: int


@pytest.mark.parametrize(
    ("amount", "expected"),
    [(450, 50), (500, 0), (199, 1), (1250, 50), (100, 0), (99, 1), (1, 99), (0, 0)],
)
def test_roundup_reaches_next_whole_unit(amount: int, expected: int) -> None:
    assert roundup_cents(amount) == expected


def test_roundup_rejects_negative_amounts() -> None:
    with pytest.raises(ValueError):
        roundup_cents(-50)


def test_income_is_never_debited_a_round_up() -> None:
    assert savings_from(1234, TransactionKind.INCOME) == 0
    assert debit_cents(1234, TransactionKind.INCOME) == 1234


def test_expense_debit_includes_the_round_up() -> None:
    assert savings_from(1250, TransactionKind.EXPENSE) == 50
    assert debit_cents(1250, TransactionKind.EXPENSE) == 1300


@pytest.mark.parametrize(
    ("saved", "target", "expected"),
    [(50, 1000, 5.0), (1000, 1000, 100.0), (0, 1000, 0.0), (0, 0, 0.0), (5, 0, 0.0)],
)
def test_progress_pct(saved: int, target: int, expected: float) -> None:
    assert progress_pct(saved, target) == expected


def test_allocate_drains_goals_oldest_first_and_never_overfills() -> None:
    goals = [FakeGoal(1, 1000), FakeGoal(2, 1000), FakeGoal(3, 1000)]

    allocations = allocate_goals(goals, 1500)

    assert [(a.goal_id, a.saved_cents) for a in allocations] == [(1, 1000), (2, 500), (3, 0)]
    assert [a.progress_pct for a in allocations] == [100.0, 50.0, 0.0]


def test_allocate_with_zero_savings_leaves_every_goal_empty() -> None:
    allocations = allocate_goals([FakeGoal(1, 5000)], 0)
    assert allocations[0].saved_cents == 0
    assert allocations[0].progress_pct == 0.0


def test_surplus_savings_are_reported_not_discarded() -> None:
    goals = [FakeGoal(1, 100), FakeGoal(2, 200)]
    allocations = allocate_goals(goals, 500)
    assert unallocated_savings(allocations, 500) == 200
    assert unallocated_savings(allocations, 300) == 0


def test_negative_savings_cannot_produce_negative_progress() -> None:
    allocations = allocate_goals([FakeGoal(1, 100)], -50)
    assert allocations[0].saved_cents == 0
    assert unallocated_savings(allocations, -50) == 0
