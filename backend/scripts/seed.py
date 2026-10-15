"""Development seed: rebuilds the demo account with a realistic 90-day ledger.

Idempotent by deletion: the demo user and everything it owns are removed
before the insert, so the script can be re-run without duplicating rows.

The ledger is generated arithmetically, not randomly: two runs produce
byte-identical data, which makes a screenshot in a bug report reproducible.

`SECRET_KEY` must be exported before running (app.security fails closed).

Run from `backend/`:  python -m scripts.seed
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import queries
from app.database import Base, SessionLocal, engine
from app.domain import TransactionKind, allocate_goals, savings_from
from app.models import Goal, Transaction, User
from app.security import hash_password
from app.services import summary

DEMO_EMAIL = "demo@pocketwise.app"
DEMO_CREDENTIAL = "Demo1234!"
HISTORY_DAYS = 90
DAY = timedelta(days=1)
OCCURRENCE_PERCENT = 14
RENT_CENTS = 78_300
PAY_DAYS = (2, 17, 32, 47, 62, 77)
VARIABLE_CATEGORIES: dict[str, tuple[int, int]] = {
    "courses": (850, 6_200),
    "transport": (150, 4_500),
    "loisirs": (900, 5_500),
    "sante": (500, 4_000),
    "energie": (4_200, 11_500),
    "telecom": (1_900, 4_800),
}
CATEGORY_SLOTS = {name: slot for slot, name in enumerate(VARIABLE_CATEGORIES)}


@dataclass(frozen=True, slots=True)
class Draft:
    kind: TransactionKind
    category: str
    amount_cents: int
    offset_days: int


def residue(offset_days: int, slot: int, step: int, salt: int) -> int:
    return (offset_days * step + slot * 29 + salt) % 100


def occurs(offset_days: int, slot: int) -> bool:
    return residue(offset_days, slot, 7, 41) < OCCURRENCE_PERCENT


def spread(low: int, high: int, offset_days: int, slot: int) -> int:
    return low + (high - low) * residue(offset_days, slot, 17, 37) // 100


def non_round(amount_cents: int, offset_days: int, slot: int) -> int:
    if amount_cents % 100:
        return amount_cents
    return amount_cents + 1 + residue(offset_days, slot, 11, 53) % 98


def expense(category: str, amount_cents: int, offset_days: int) -> Draft:
    return Draft(TransactionKind.EXPENSE, category, amount_cents, offset_days)


def income(category: str, amount_cents: int, offset_days: int) -> Draft:
    return Draft(TransactionKind.INCOME, category, amount_cents, offset_days)


def build_ledger() -> list[Draft]:
    drafts = [income("salaire", 248_740, offset) for offset in PAY_DAYS]
    drafts.append(income("freelance", 62_500, 9))
    drafts.append(income("freelance", 48_300, 41))
    for offset in (3, 33):
        drafts.append(expense("loyer", RENT_CENTS, offset))
    drafts.append(expense("energie", 6_180, 5))
    drafts.append(expense("energie", 5_420, 35))
    drafts.append(expense("telecom", 2_990, 6))
    for slot, (category, bounds) in enumerate(VARIABLE_CATEGORIES.items()):
        for offset in range(HISTORY_DAYS):
            if occurs(offset, slot):
                drafts.append(expense(category, spread(*bounds, offset, slot), offset))
    return drafts


def insert_transactions(db: Session, user_id: int, today: date) -> int:
    drafts = build_ledger()
    rows: list[Transaction] = []
    for draft in drafts:
        amount = draft.amount_cents
        if draft.kind is TransactionKind.EXPENSE and draft.category != "loyer":
            amount = non_round(amount, draft.offset_days, CATEGORY_SLOTS[draft.category])
        rows.append(
            Transaction(
                user_id=user_id,
                kind=draft.kind,
                category=draft.category,
                amount_cents=amount,
                roundup_cents=savings_from(amount, draft.kind),
                occurred_on=today - draft.offset_days * DAY,
            )
        )
    db.add_all(rows)
    db.commit()
    return len(rows)


def insert_goals(db: Session, user_id: int) -> list[Goal]:
    goals = [
        Goal(user_id=user_id, name="Cadeau anniversaire", target_cents=1_200),
        Goal(user_id=user_id, name="Nouveau velo", target_cents=60_000),
        Goal(user_id=user_id, name="Fonds de securite", target_cents=120_000),
    ]
    db.add_all(goals)
    db.commit()
    for goal in goals:
        db.refresh(goal)
    return goals


def wipe_demo(db: Session) -> None:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user is None:
        return
    db.execute(delete(Transaction).where(Transaction.user_id == user.id))
    db.execute(delete(Goal).where(Goal.user_id == user.id))
    db.delete(user)
    db.commit()


def bare(cents: int) -> str:
    return f"{cents / 100:.2f}".replace(".", ",")


def amount(cents: int) -> str:
    return f"{bare(cents)} EUR"


def report(db: Session, user_id: int) -> None:
    user = db.get(User, user_id)
    if user is None:
        return
    data = summary("all", db, user)
    savings = data.roundup_savings_cents
    goals = queries.list_goals(db, user_id)
    allocations = allocate_goals(goals, savings)
    sample = 1_250
    roundup = savings_from(sample, TransactionKind.EXPENSE)
    print()
    print("PocketWise - donnees de demonstration")
    print("=" * 64)
    print(f"  Courriel        : {DEMO_EMAIL}")
    print(f"  Mot de passe    : {DEMO_CREDENTIAL}")
    print("  API locale      : http://localhost:8000")
    print("  Interface locale: http://localhost:5173")
    print("-" * 64)
    print(f"  Transactions    : {data.transaction_count}")
    print(f"  Revenus         : {amount(data.income_cents)}")
    print(f"  Depenses        : {amount(data.expense_cents)}  (montant reellement debite)")
    print(f"  Solde           : {amount(data.balance_cents)}")
    print(f"  Epargne arrondi : {amount(savings)}")
    print(f"  Non alloue      : {amount(data.unallocated_savings_cents)}")
    print("-" * 64)
    for goal, allocation in zip(goals, allocations, strict=True):
        progress = f"{bare(allocation.saved_cents):>10} / {bare(goal.target_cents):>10}"
        print(f"  {goal.name:<20} {progress} EUR  ({allocation.progress_pct} %)")
    print("-" * 64)
    print(
        f"  Exemple         : {bare(sample)} EUR de depense -> "
        f"{bare(sample + roundup)} EUR debites, {bare(roundup)} EUR epargnes"
    )
    print("=" * 64)
    print()


def main() -> None:
    target = os.getenv("DATABASE_URL") or "sqlite:///./pocketwise.db (defaut)"
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        wipe_demo(db)
        user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_CREDENTIAL))
        db.add(user)
        db.commit()
        db.refresh(user)
        inserted = insert_transactions(db, user.id, date.today())
        goals = insert_goals(db, user.id)
        print(f"Cible : {target}")
        print(f"{inserted} transactions inserees, {len(goals)} objectifs crees.")
        report(db, user.id)


if __name__ == "__main__":
    main()
