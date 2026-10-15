from __future__ import annotations

from datetime import date, timedelta

import pytest
from conftest import auth, register
from fastapi.testclient import TestClient


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return auth(register(client, "ledger@example.com"))


def test_expense_round_up_is_actually_debited(client: TestClient, headers) -> None:
    assert (
        client.post(
            "/transactions",
            headers=headers,
            json={"kind": "income", "category": "salary", "amount_cents": 50000},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/transactions",
            headers=headers,
            json={"kind": "expense", "category": "Food", "amount_cents": 1250},
        ).status_code
        == 201
    )

    summary = client.get("/summary", headers=headers).json()

    assert summary["expense_cents"] == 1300
    assert summary["balance_cents"] == 50000 - 1300
    assert summary["roundup_savings_cents"] == 50


def test_income_is_not_rounded_up(client: TestClient, headers) -> None:
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "income", "category": "salary", "amount_cents": 12345},
    )

    listed = client.get("/transactions", headers=headers).json()["items"]

    assert listed[0]["roundup_cents"] == 0
    assert client.get("/summary", headers=headers).json()["roundup_savings_cents"] == 0


def test_category_is_normalised(client: TestClient, headers) -> None:
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "  Groceries  ", "amount_cents": 999},
    )
    assert (
        client.get("/transactions", headers=headers).json()["items"][0]["category"] == "groceries"
    )


def test_occurred_on_defaults_to_today_and_accepts_a_client_date(
    client: TestClient, headers
) -> None:
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "x", "amount_cents": 100},
    )
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "y", "amount_cents": 100, "occurred_on": "2024-01-15"},
    )

    items = client.get("/transactions", headers=headers).json()["items"]

    assert items[0]["occurred_on"] == str(date.today())
    assert items[1]["occurred_on"] == "2024-01-15"


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "expense", "category": "x", "amount_cents": -5},
        {"kind": "expense", "category": "x", "amount_cents": 0},
        {"kind": "expense", "category": "", "amount_cents": 100},
        {"kind": "transfer", "category": "x", "amount_cents": 100},
        {"kind": "expense", "category": "x"},
        {"kind": "expense", "category": "x", "amount_cents": 10**9},
    ],
)
def test_invalid_transactions_are_rejected(client: TestClient, headers, payload) -> None:
    assert client.post("/transactions", headers=headers, json=payload).status_code == 422


def test_client_supplied_ownership_fields_are_ignored(client: TestClient, headers) -> None:
    response = client.post(
        "/transactions",
        headers=headers,
        json={
            "kind": "expense",
            "category": "x",
            "amount_cents": 100,
            "id": 4242,
            "user_id": 999,
            "roundup_cents": 999999,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["roundup_cents"] == 0
    assert body["id"] != 4242


def test_listing_is_paginated_and_ordered(client: TestClient, headers) -> None:
    for day in range(1, 13):
        client.post(
            "/transactions",
            headers=headers,
            json={
                "kind": "expense",
                "category": "x",
                "amount_cents": 100,
                "occurred_on": str(date(2024, 1, 1) + timedelta(days=day - 1)),
            },
        )

    first_page = client.get("/transactions?limit=5&offset=0", headers=headers).json()
    second_page = client.get("/transactions?limit=5&offset=5", headers=headers).json()

    assert first_page["total"] == 12
    assert len(first_page["items"]) == 5
    assert len(second_page["items"]) == 5
    dates = [item["occurred_on"] for item in first_page["items"]]
    assert dates == sorted(dates, reverse=True)
    assert {i["id"] for i in first_page["items"]}.isdisjoint(
        {i["id"] for i in second_page["items"]}
    )


def test_transactions_beyond_the_page_are_still_reachable(client: TestClient, headers) -> None:
    for _ in range(60):
        client.post(
            "/transactions",
            headers=headers,
            json={"kind": "expense", "category": "x", "amount_cents": 100},
        )
    created = client.get("/transactions?limit=50", headers=headers).json()["items"][-1]["id"]
    assert client.delete(f"/transactions/{created}", headers=headers).status_code == 204


def test_period_filter_narrows_the_window(client: TestClient, headers) -> None:
    client.post(
        "/transactions",
        headers=headers,
        json={
            "kind": "expense",
            "category": "old",
            "amount_cents": 1250,
            "occurred_on": str(date.today() - timedelta(days=400)),
        },
    )
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "new", "amount_cents": 999},
    )

    assert client.get("/summary?period=all", headers=headers).json()["transaction_count"] == 2
    assert client.get("/summary?period=year", headers=headers).json()["transaction_count"] == 1
    assert client.get("/summary?period=month", headers=headers).json()["transaction_count"] == 1
    assert client.get("/transactions?period=year", headers=headers).json()["total"] == 1


def test_invalid_period_is_rejected(client: TestClient, headers) -> None:
    assert client.get("/summary?period=decade", headers=headers).status_code == 422


def test_spending_by_category_is_aggregated_and_ranked(client: TestClient, headers) -> None:
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "food", "amount_cents": 1250},
    )
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "food", "amount_cents": 750},
    )
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "rent", "amount_cents": 90000},
    )
    client.post(
        "/transactions",
        headers=headers,
        json={"kind": "income", "category": "salary", "amount_cents": 50000},
    )

    buckets = client.get("/summary", headers=headers).json()["spending_by_category"]

    assert buckets == [{"category": "rent", "cents": 90000}, {"category": "food", "cents": 2000}]
    assert client.get("/summary", headers=headers).json()["unallocated_savings_cents"] == 100


def test_deleting_an_expense_rolls_savings_and_goals_back(client: TestClient, headers) -> None:
    created = client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "x", "amount_cents": 1250},
    ).json()
    client.post("/goals", headers=headers, json={"name": "Laptop", "target_cents": 1000})
    assert client.get("/summary", headers=headers).json()["roundup_savings_cents"] == 50
    assert client.get("/goals", headers=headers).json()[0]["progress_pct"] == 5.0

    assert client.delete(f"/transactions/{created['id']}", headers=headers).status_code == 204

    summary = client.get("/summary", headers=headers).json()
    assert summary["roundup_savings_cents"] == 0
    assert summary["expense_cents"] == 0
    assert client.get("/goals", headers=headers).json()[0]["progress_pct"] == 0.0


def test_savings_survive_account_with_no_transactions(client: TestClient, headers) -> None:
    summary = client.get("/summary", headers=headers).json()
    assert summary == {
        "income_cents": 0,
        "expense_cents": 0,
        "balance_cents": 0,
        "roundup_savings_cents": 0,
        "unallocated_savings_cents": 0,
        "transaction_count": 0,
        "spending_by_category": [],
    }


def test_health_endpoint_reports_ok(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
