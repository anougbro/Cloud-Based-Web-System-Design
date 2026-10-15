from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from .. import audit, queries, services
from ..database import get_db
from ..models import User
from ..schemas import GoalIn, GoalOut, SummaryOut, TransactionIn, TransactionOut, TransactionPage
from ..security import current_user

router = APIRouter(tags=["ledger"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]


@router.post(
    "/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(body: TransactionIn, user: CurrentUser, db: DbSession) -> TransactionOut:
    return services.create_transaction(body, db, user)


@router.get("/transactions", response_model=TransactionPage)
def list_transactions(
    user: CurrentUser,
    db: DbSession,
    period: Annotated[str, Query(pattern="^(all|month|year)$")] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TransactionPage:
    """Paginated history.

    Pagination is not cosmetic: a hard 200-row cap silently hid older rows
    from the delete control in the UI, making them unreachable and undeletable.
    """
    return services.list_transactions(period, limit, offset, db, user)


@router.delete("/transactions/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(tx_id: int, request: Request, user: CurrentUser, db: DbSession) -> Response:
    tx = queries.owned_transaction(db, tx_id, user.id)
    if tx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    db.delete(tx)
    db.commit()
    audit.audit(
        "transaction_deleted",
        tx_id=tx_id,
        user_id=user.id,
        ip=request.client.host if request.client else "unknown",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/summary", response_model=SummaryOut)
def summary(
    user: CurrentUser,
    db: DbSession,
    period: Annotated[str, Query(pattern="^(all|month|year)$")] = "all",
) -> SummaryOut:
    return services.summary(period, db, user)


@router.post("/goals", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(body: GoalIn, user: CurrentUser, db: DbSession) -> GoalOut:
    return services.create_goal(body, db, user)


@router.get("/goals", response_model=list[GoalOut])
def list_goals(user: CurrentUser, db: DbSession) -> list[GoalOut]:
    return services.list_goals(db, user)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, request: Request, user: CurrentUser, db: DbSession) -> Response:
    goal = queries.owned_goal(db, goal_id, user.id)
    if goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    db.delete(goal)
    db.commit()
    audit.audit(
        "goal_deleted",
        goal_id=goal_id,
        user_id=user.id,
        ip=request.client.host if request.client else "unknown",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
