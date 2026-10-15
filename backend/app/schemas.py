from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from .domain import MAX_AMOUNT_CENTS

Category = Annotated[str, Field(min_length=1, max_length=50)]
AmountCents = Annotated[int, Field(gt=0, lt=MAX_AMOUNT_CENTS)]
Period = Literal["all", "month", "year"]


class Credentials(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=8, max_length=128)]


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TransactionIn(BaseModel):
    kind: Literal["income", "expense"]
    category: Category
    amount_cents: AmountCents
    occurred_on: date | None = None


class TransactionOut(BaseModel):
    id: int
    kind: str
    category: str
    amount_cents: int
    roundup_cents: int
    occurred_on: date
    model_config = {"from_attributes": True}


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int
    limit: int
    offset: int


class GoalIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]
    target_cents: AmountCents


class GoalOut(BaseModel):
    id: int
    name: str
    target_cents: int
    saved_cents: int
    progress_pct: float


class CategorySpend(BaseModel):
    category: str
    cents: int


class SummaryOut(BaseModel):
    income_cents: int
    expense_cents: int
    balance_cents: int
    roundup_savings_cents: int
    unallocated_savings_cents: int
    transaction_count: int
    spending_by_category: list[CategorySpend]
