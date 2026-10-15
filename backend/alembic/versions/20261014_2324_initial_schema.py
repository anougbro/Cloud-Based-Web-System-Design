"""Initial schema.

Creates users, transactions, goals and revoked_tokens, together with the
database-level constraints that keep the domain rules true even when a write
bypasses the API layer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e681cc9ec1af"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND = sa.Enum(
    "income",
    "expense",
    name="transaction_kind",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", KIND, nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("roundup_cents", sa.Integer(), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.CheckConstraint("amount_cents > 0", name="ck_transaction_amount_positive"),
        sa.CheckConstraint("roundup_cents >= 0", name="ck_transaction_roundup_non_negative"),
        sa.CheckConstraint(
            "roundup_cents < 100 AND (kind = 'expense' OR roundup_cents = 0)",
            name="ck_transaction_roundup_only_on_expense",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.create_index("ix_transaction_user_recent", ["user_id", "occurred_on", "id"])
        batch_op.create_index(batch_op.f("ix_transactions_occurred_on"), ["occurred_on"])

    op.create_table(
        "goals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("target_cents", sa.Integer(), nullable=False),
        sa.CheckConstraint("target_cents > 0", name="ck_goal_target_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("goals") as batch_op:
        batch_op.create_index(batch_op.f("ix_goals_user_id"), ["user_id"])

    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("revoked_tokens") as batch_op:
        batch_op.create_index(batch_op.f("ix_revoked_tokens_jti"), ["jti"], unique=True)
        batch_op.create_index(batch_op.f("ix_revoked_tokens_expires_at"), ["expires_at"])


def downgrade() -> None:
    op.drop_table("revoked_tokens")
    op.drop_table("goals")
    op.drop_table("transactions")
    op.drop_table("users")
