"""Regression tests for two rules the app relies on.

* A **price** (what the form sends, and what the mock-up shows) is a major-unit
  amount: ``49`` and ``"49.00"`` both mean ``€49.00``.  A plan stored in the
  database is **integer cents**: ``4900`` means ``€49.00``.  Keeping these apart
  is what stopped the plan catalogue from multiplying a user price by 100.
* A cancellation needs an ``end_date`` on or after the subscription's start date,
  and cancelling one subscription must not touch another.

``check_books_balance`` is the one checker run at the end of the unit tests: the
summary the API reports must agree with the rows it is built from.
"""

from __future__ import annotations

import pytest

from meteroid import billing
from meteroid.billing import BillingError


def check_books_balance(conn):
    """Invariant: the summary MRR agrees with the active rows."""
    rows = billing.subscription_rows(conn)
    expected = sum(r["mrr_cents"] for r in rows if r["status"] == "active")
    assert billing.summary(conn)["mrr_cents"] == expected
    assert billing.summary(conn)["subscriptions"] == len(rows)


# ------------------------------------------------------------------- money
def test_a_price_is_major_units_but_a_stored_plan_is_cents(conn):
    # parse_amount_cents reads a price: 49 -> 4900 cents.
    assert billing.parse_amount_cents(49) == 4900
    assert billing.parse_amount_cents(49.5) == 4950
    assert billing.parse_amount_cents("49") == 4900
    # create_plan already takes cents, so 4900 stays 4900.
    plan = billing.create_plan(conn, "Starter", 4900)
    assert plan["amount_cents"] == 4900
    assert billing.format_amount(plan["amount_cents"]) == "\u20ac49.00"
    check_books_balance(conn)


def test_a_plan_must_be_a_whole_non_negative_amount(conn):
    with pytest.raises(BillingError):
        billing.create_plan(conn, "P", -1)
    with pytest.raises(BillingError):
        billing.create_plan(conn, "P", "abc")
    assert conn.execute("SELECT COUNT(*) AS n FROM plans").fetchone()["n"] == 0


def test_plan_amount_over_http_accepts_a_price_or_integer_cents(client):
    # A price string is what the "New plan" form sends.
    assert client.post("/api/plans", {"name": "A", "amount": "49.00"})[1]["amount_cents"] == 4900
    # A numeric JSON price is a price too.
    assert client.post("/api/plans", {"name": "B", "amount": 49})[1]["amount_cents"] == 4900
    # amount_cents is already cents.
    assert client.post("/api/plans", {"name": "C", "amount_cents": 4900})[1]["amount_cents"] == 4900

    for name, amount in (("D", "-1"), ("E", "abc"), ("F", None)):
        status, body = client.post("/api/plans", {"name": name, "amount": amount})
        assert status == 400 and body["error"], (name, body)


# ------------------------------------------------------------ cancellation
def test_cancel_accepts_the_start_date_but_not_the_day_before(client):
    customer = client.post("/api/customers", {"name": "Acme"})[1]
    plan = client.post("/api/plans", {"name": "Starter", "amount": "49.00"})[1]

    def subscribe():
        return client.post("/api/subscriptions", {
            "customer_id": customer["id"], "plan_id": plan["id"], "start_date": "2025-12-02",
        })[1]

    on_start = subscribe()
    status, body = client.post(f"/api/subscriptions/{on_start['id']}/cancel", {"end_date": "2025-12-02"})
    assert status == 200 and body["end_date"] == "2025-12-02", body

    too_early = subscribe()
    status, body = client.post(f"/api/subscriptions/{too_early['id']}/cancel", {"end_date": "2025-12-01"})
    assert status == 400 and body["error"], body
    # The rejected cancellation changed nothing.
    assert client.get(f"/api/subscriptions/{too_early['id']}")[1]["status"] == "active"


def test_cancelling_one_subscription_leaves_another_alone(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 4900)
    keep = billing.create_subscription(conn, customer["id"], plan["id"], "active", "2025-12-02")
    drop = billing.create_subscription(conn, customer["id"], plan["id"], "active", "2025-12-03")

    billing.cancel_subscription(conn, drop["id"], "2025-12-10")

    assert [i["status"] for i in billing.invoice_rows(conn, keep["id"])] == ["open"]
    assert [i["status"] for i in billing.invoice_rows(conn, drop["id"])] == ["void"]
    assert billing.get_subscription(conn, keep["id"])["end_date"] is None
    check_books_balance(conn)
