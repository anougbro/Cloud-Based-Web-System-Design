from __future__ import annotations

import pytest
from conftest import auth, register
from fastapi.testclient import TestClient


@pytest.fixture
def headers(client: TestClient) -> dict[str, str]:
    return auth(register(client, "goals@example.com"))


def spend(client: TestClient, headers, amount_cents: int) -> None:
    response = client.post(
        "/transactions",
        headers=headers,
        json={"kind": "expense", "category": "x", "amount_cents": amount_cents},
    )
    assert response.status_code == 201


def test_goal_is_created_empty_when_there_is_no_savings(client: TestClient, headers) -> None:
    goal = client.post("/goals", headers=headers, json={"name": "Laptop", "target_cents": 1000})

    assert goal.status_code == 201
    assert goal.json() == {
        "id": goal.json()["id"],
        "name": "Laptop",
        "target_cents": 1000,
        "saved_cents": 0,
        "progress_pct": 0.0,
    }


def test_round_up_savings_fill_goals_in_creation_order(client: TestClient, headers) -> None:
    spend(client, headers, 1499)
    first = client.post("/goals", headers=headers, json={"name": "First", "target_cents": 100})
    second = client.post("/goals", headers=headers, json={"name": "Second", "target_cents": 1000})

    assert client.get("/goals", headers=headers).json() == [
        {
            "id": first.json()["id"],
            "name": "First",
            "target_cents": 100,
            "saved_cents": 1,
            "progress_pct": 1.0,
        },
        {
            "id": second.json()["id"],
            "name": "Second",
            "target_cents": 1000,
            "saved_cents": 0,
            "progress_pct": 0.0,
        },
    ]


def test_second_goal_is_never_double_counted_by_its_own_creation_response(
    client: TestClient, headers
) -> None:
    spend(client, headers, 1499)
    first = client.post("/goals", headers=headers, json={"name": "First", "target_cents": 100})
    second = client.post("/goals", headers=headers, json={"name": "Second", "target_cents": 1000})

    listed = {g["id"]: g for g in client.get("/goals", headers=headers).json()}
    assert second.json() == listed[second.json()["id"]]
    assert first.json() == listed[first.json()["id"]]


def test_savings_cascade_across_several_goals(client: TestClient, headers) -> None:
    for _ in range(3):
        spend(client, headers, 1950)
    for name, target in (("A", 100), ("B", 200), ("C", 300)):
        client.post("/goals", headers=headers, json={"name": name, "target_cents": target})

    goals = client.get("/goals", headers=headers).json()

    assert [(g["name"], g["saved_cents"], g["progress_pct"]) for g in goals] == [
        ("A", 100, 100.0),
        ("B", 50, 25.0),
        ("C", 0, 0.0),
    ]
    assert client.get("/summary", headers=headers).json()["unallocated_savings_cents"] == 0


def test_surplus_beyond_every_goal_is_reported(client: TestClient, headers) -> None:
    spend(client, headers, 1901)
    spend(client, headers, 1950)
    client.post("/goals", headers=headers, json={"name": "A", "target_cents": 100})

    summary = client.get("/summary", headers=headers).json()
    goals = client.get("/goals", headers=headers).json()

    assert summary["roundup_savings_cents"] == 149
    assert summary["unallocated_savings_cents"] == 49
    assert goals[0]["saved_cents"] == 100
    assert goals[0]["progress_pct"] == 100.0


def test_deleting_the_earliest_goal_refunds_the_next_one(client: TestClient, headers) -> None:
    spend(client, headers, 1499)
    first = client.post("/goals", headers=headers, json={"name": "First", "target_cents": 100})
    second = client.post("/goals", headers=headers, json={"name": "Second", "target_cents": 1000})
    assert client.get("/goals", headers=headers).json()[1]["saved_cents"] == 0

    assert client.delete(f"/goals/{first.json()['id']}", headers=headers).status_code == 204

    goals = client.get("/goals", headers=headers).json()
    assert [g["id"] for g in goals] == [second.json()["id"]]
    assert goals[0]["saved_cents"] == 1
    assert goals[0]["progress_pct"] == 0.1


def test_goal_name_is_trimmed(client: TestClient, headers) -> None:
    goal = client.post("/goals", headers=headers, json={"name": "  Laptop  ", "target_cents": 1000})
    assert goal.json()["name"] == "Laptop"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "x", "target_cents": 0},
        {"name": "x", "target_cents": -100},
        {"name": "", "target_cents": 100},
        {"name": "x"},
    ],
)
def test_invalid_goals_are_rejected(client: TestClient, headers, payload) -> None:
    assert client.post("/goals", headers=headers, json=payload).status_code == 422


def test_unknown_goal_delete_is_not_found(client: TestClient, headers) -> None:
    assert client.delete("/goals/424242", headers=headers).status_code == 404


def test_cannot_delete_another_users_goal(client: TestClient, headers) -> None:
    victim = client.post("/goals", headers=headers, json={"name": "Private", "target_cents": 1000})
    attacker = auth(register(client, "attacker@example.com"))

    assert client.delete(f"/goals/{victim.json()['id']}", headers=attacker).status_code == 404
    assert [g["id"] for g in client.get("/goals", headers=headers).json()] == [victim.json()["id"]]


def test_users_cannot_see_each_others_transactions_or_summary(client: TestClient) -> None:
    victim = auth(register(client, "victim@example.com"))
    attacker = auth(register(client, "intruder@example.com"))
    spend(client, victim, 1250)
    client.post("/goals", headers=victim, json={"name": "Secret", "target_cents": 50000})

    assert client.get("/transactions", headers=attacker).json()["total"] == 0
    assert client.get("/summary", headers=attacker).json()["spending_by_category"] == []
    assert client.get("/goals", headers=attacker).json() == []


def test_cannot_delete_another_users_transaction(client: TestClient) -> None:
    victim = auth(register(client, "victim@example.com"))
    attacker = auth(register(client, "intruder@example.com"))
    created = client.post(
        "/transactions",
        headers=victim,
        json={"kind": "expense", "category": "x", "amount_cents": 100},
    ).json()

    assert client.delete(f"/transactions/{created['id']}", headers=attacker).status_code == 404
    assert client.get("/transactions", headers=victim).json()["total"] == 1
    assert client.delete(f"/transactions/{created['id']}", headers=victim).status_code == 204
