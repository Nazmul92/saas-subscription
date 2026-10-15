"""Spec tests for premium access (``billing.has_premium_access``).

The rule the app promises (``meteroid.billing``'s module docstring, and the
``premium`` field on ``GET /api/customers``): a customer may use the paid
features **only while they hold an active subscription whose term has not
ended** - ``end_date`` is null (open-ended), or today or later.

So a subscription that has lapsed (``end_date`` in the past while its status has
not been reconciled to ``canceled`` yet) grants **no** access, and neither does a
pending or canceled one.  The demo data ships two such lapsed customers on
purpose, so the Customers page has real cases to show.

Boundary cases are expressed relative to ``date.today()`` so they stay honest.
"""

from __future__ import annotations

import datetime as dt

import pytest

from meteroid import billing

TODAY = dt.date.today()


def _days(offset: int) -> str:
    return (TODAY + dt.timedelta(days=offset)).isoformat()


def _customer(conn, name="Acme Ltd", email=None):
    return billing.create_customer(conn, name, email)


def _plan(conn, name="Starter", amount=5000):
    return billing.create_plan(conn, name, amount)


def _sub(conn, customer, plan, status="active", start="2025-01-01", end=None):
    return billing.create_subscription(conn, customer["id"], plan["id"], status, start, end)


def _expected_access(conn, customer_id: int) -> bool:
    """The rule re-stated straight from the stored rows, as a cross-check."""
    rows = conn.execute(
        "SELECT status, end_date FROM subscriptions WHERE customer_id = ?", (customer_id,)
    ).fetchall()
    return any(
        r["status"] == "active" and (r["end_date"] is None or r["end_date"] >= TODAY.isoformat())
        for r in rows
    )


# ------------------------------------------------------------------- granted
def test_open_ended_active_subscription_grants_access(conn):
    customer = _customer(conn)
    _sub(conn, customer, _plan(conn), "active", "2025-01-01", None)
    assert billing.has_premium_access(conn, customer["id"]) is True


def test_active_subscription_with_a_future_term_end_grants_access(conn):
    customer = _customer(conn)
    _sub(conn, customer, _plan(conn), "active", "2025-01-01", _days(30))
    assert billing.has_premium_access(conn, customer["id"]) is True


def test_a_term_that_ends_today_still_grants_access(conn):
    """The last day of the term is still inside the term."""
    customer = _customer(conn)
    _sub(conn, customer, _plan(conn), "active", "2025-01-01", _days(0))
    assert billing.has_premium_access(conn, customer["id"]) is True


# --------------------------------------------------------------------- denied
@pytest.mark.parametrize("offset", [-1, -30, -365])
def test_lapsed_active_subscription_grants_no_access(conn, offset):
    """An expired subscription keeps working only if nobody checks its end date."""
    customer = _customer(conn)
    _sub(conn, customer, _plan(conn), "active", "2025-01-01", _days(offset))
    assert billing.has_premium_access(conn, customer["id"]) is False


def test_canceled_subscription_grants_no_access(conn):
    customer = _customer(conn)
    sub = _sub(conn, customer, _plan(conn), "active", "2025-01-01")
    billing.cancel_subscription(conn, sub["id"], _days(30))
    assert billing.has_premium_access(conn, customer["id"]) is False


def test_pending_subscription_grants_no_access(conn):
    customer = _customer(conn)
    _sub(conn, customer, _plan(conn), "pending", "2025-01-01")
    assert billing.has_premium_access(conn, customer["id"]) is False


def test_a_customer_without_subscriptions_has_no_access(conn):
    customer = _customer(conn)
    assert billing.has_premium_access(conn, customer["id"]) is False


def test_an_unknown_customer_has_no_access(conn):
    assert billing.has_premium_access(conn, 9999) is False


# --------------------------------------------------------------- break-it style
def test_one_current_subscription_outweighs_a_lapsed_one(conn):
    customer = _customer(conn)
    plan = _plan(conn)
    _sub(conn, customer, plan, "active", "2025-01-01", _days(-90))
    _sub(conn, customer, plan, "active", "2025-01-01", None)
    assert billing.has_premium_access(conn, customer["id"]) is True


def test_a_lapsed_subscription_does_not_leak_to_another_customer(conn):
    """The same plan, two owners: only the one whose term is live gets access."""
    plan = _plan(conn)
    lapsed = _customer(conn, "Cobalt Industries SAS", "a@cobalt.example")
    live = _customer(conn, "Pulse Analytics GmbH", "b@pulse.example")
    _sub(conn, lapsed, plan, "active", "2025-01-01", _days(-1))
    _sub(conn, live, plan, "active", "2025-01-01", None)
    assert billing.has_premium_access(conn, lapsed["id"]) is False
    assert billing.has_premium_access(conn, live["id"]) is True


def test_access_is_decided_per_customer_not_per_name(conn):
    plan = _plan(conn)
    first = _customer(conn, "Acme Ltd", "one@acme.example")
    second = _customer(conn, "Acme Ltd", "two@acme.example")
    _sub(conn, first, plan, "active", "2025-01-01", _days(-1))
    _sub(conn, second, plan, "active", "2025-01-01", None)
    assert billing.has_premium_access(conn, first["id"]) is False
    assert billing.has_premium_access(conn, second["id"]) is True


def test_the_order_of_the_subscriptions_does_not_matter(conn):
    plan = _plan(conn)
    oldest_lapsed = _customer(conn, "Oldest Lapsed", "a@x.example")
    newest_lapsed = _customer(conn, "Newest Lapsed", "b@x.example")
    _sub(conn, oldest_lapsed, plan, "active", "2025-01-01", _days(-1))
    _sub(conn, oldest_lapsed, plan, "active", "2025-01-01", _days(-30))
    _sub(conn, newest_lapsed, plan, "active", "2025-01-01", _days(-30))
    _sub(conn, newest_lapsed, plan, "active", "2025-01-01", _days(-1))
    assert billing.has_premium_access(conn, oldest_lapsed["id"]) is False
    assert billing.has_premium_access(conn, newest_lapsed["id"]) is False


def test_a_live_term_is_found_whichever_row_it_is(conn):
    plan = _plan(conn)
    lapsed_first = _customer(conn, "Lapsed First", "c@x.example")
    current_first = _customer(conn, "Current First", "d@x.example")
    _sub(conn, lapsed_first, plan, "active", "2025-01-01", _days(-1))
    _sub(conn, lapsed_first, plan, "active", "2025-01-01", _days(5))
    _sub(conn, current_first, plan, "active", "2025-01-01", _days(5))
    _sub(conn, current_first, plan, "active", "2025-01-01", _days(-1))
    assert billing.has_premium_access(conn, lapsed_first["id"]) is True
    assert billing.has_premium_access(conn, current_first["id"]) is True


# -------------------------------------------------------------------- checker
def test_checker_access_matches_the_stored_rows(seeded):
    """One check over every seeded customer: the flag must equal the rule."""
    live = {
        row["customer_id"]
        for row in seeded.execute(
            "SELECT DISTINCT customer_id FROM subscriptions WHERE status = 'active'"
            " AND (end_date IS NULL OR end_date >= ?)",
            (TODAY.isoformat(),),
        ).fetchall()
    }
    for customer in billing.list_customers(seeded):
        assert billing.has_premium_access(seeded, customer["id"]) == (
            customer["id"] in live
        ), f"{customer['name']} disagrees with its stored rows"
        assert billing.has_premium_access(seeded, customer["id"]) == _expected_access(
            seeded, customer["id"]
        )


def test_checking_access_does_not_write_anything(conn):
    customer = _customer(conn)
    _sub(conn, customer, _plan(conn), "active", "2025-01-01", _days(-1))
    before = conn.total_changes
    billing.has_premium_access(conn, customer["id"])
    assert conn.total_changes == before


# ------------------------------------------------------------- the demo data
def test_seeded_lapsed_customers_have_no_access(seeded):
    ids = {row["name"]: row["id"] for row in billing.list_customers(seeded)}
    assert billing.has_premium_access(seeded, ids["Pulse Analytics GmbH"]) is True
    assert billing.has_premium_access(seeded, ids["Cobalt Industries SAS"]) is False
    assert billing.has_premium_access(seeded, ids["Evergreen Dynamics Ltd"]) is False


# -------------------------------------------------------------------- HTTP API
def test_customers_endpoint_reports_premium_access(client):
    _, customer = client.post(
        "/api/customers", {"name": "Lapsed Ltd", "email": "billing@lapsed.example"}
    )
    _, plan = client.post("/api/plans", {"name": "Starter", "amount": "49.00"})
    status, _ = client.post(
        "/api/subscriptions",
        {
            "customer_id": customer["id"],
            "plan_id": plan["id"],
            "start_date": "2025-01-01",
            "end_date": _days(-1),
        },
    )
    assert status == 201

    items = client.get("/api/customers")[1]["items"]
    assert items[0]["name"] == "Lapsed Ltd"
    assert items[0]["premium"] is False


def test_customers_endpoint_reports_access_for_a_live_term(client):
    _, customer = client.post("/api/customers", {"name": "Current Ltd"})
    _, plan = client.post("/api/plans", {"name": "Starter", "amount": "49.00"})
    client.post(
        "/api/subscriptions",
        {"customer_id": customer["id"], "plan_id": plan["id"], "start_date": "2025-01-01"},
    )
    assert client.get("/api/customers")[1]["items"][0]["premium"] is True
