"""Unit tests for the billing rules in meteroid.billing."""

from __future__ import annotations

import datetime as dt

import pytest

from meteroid import billing
from meteroid.billing import BillingError


# --------------------------------------------------------------------- money
def test_amount_parsing_accepts_common_forms():
    assert billing.parse_amount_cents(49) == 4900
    assert billing.parse_amount_cents(49.5) == 4950
    assert billing.parse_amount_cents("49") == 4900
    assert billing.parse_amount_cents("49.00") == 4900
    assert billing.parse_amount_cents("\u20ac1,234.50") == 123450
    assert billing.parse_amount_cents("0") == 0


@pytest.mark.parametrize("bad", ["", "abc", "-5", -5, None, True, []])
def test_amount_parsing_rejects_bad_input(bad):
    with pytest.raises(BillingError):
        billing.parse_amount_cents(bad)


def test_money_is_exact_integer_cents():
    # 0.1 + 0.2 style drift must not appear: everything is integer cents.
    total = sum(billing.parse_amount_cents(x) for x in ["0.10", "0.20"])
    assert total == 30
    assert billing.format_amount(total) == "\u20ac0.30"


@pytest.mark.parametrize(
    "cents,currency,expected",
    [
        (7000, "EUR", "\u20ac70.00"),
        (102900, "EUR", "\u20ac1,029.00"),
        (49900, "USD", "$499.00"),
        (0, "GBP", "\u00a30.00"),
        (1000, "SEK", "10.00 SEK"),
    ],
)
def test_format_amount(cents, currency, expected):
    assert billing.format_amount(cents, currency) == expected


# ------------------------------------------------------------ interval + MRR
def test_add_interval_clamps_short_months():
    assert billing.add_interval(dt.date(2025, 1, 31), "month") == dt.date(2025, 2, 28)
    assert billing.add_interval(dt.date(2024, 1, 31), "month") == dt.date(2024, 2, 29)
    assert billing.add_interval(dt.date(2025, 12, 2), "month") == dt.date(2026, 1, 2)
    assert billing.add_interval(dt.date(2025, 3, 1), "year") == dt.date(2026, 3, 1)


def test_monthly_cents_normalises_yearly_plans():
    assert billing.monthly_cents(7000, "month") == 7000
    assert billing.monthly_cents(120000, "year") == 10000  # 1200.00 / 12
    assert billing.monthly_cents(49900, "year") == 4158  # rounds to whole cents


def test_monthly_cents_rejects_unknown_interval():
    with pytest.raises(BillingError):
        billing.monthly_cents(100, "week")


def test_parse_date_accepts_iso_only():
    assert billing.parse_date("2025-12-02") == dt.date(2025, 12, 2)
    assert billing.parse_date(dt.date(2025, 1, 1)) == dt.date(2025, 1, 1)
    with pytest.raises(BillingError):
        billing.parse_date("02/12/2025")


# ----------------------------------------------------------------- customers
def test_create_customer_requires_a_name(conn):
    with pytest.raises(BillingError):
        billing.create_customer(conn, "   ")
    assert conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"] == 0


def test_create_customer_rejects_a_duplicate_email(conn):
    billing.create_customer(conn, "Acme", "billing@acme.example")
    with pytest.raises(BillingError):
        billing.create_customer(conn, "Acme Two", "billing@acme.example")


def test_two_customers_may_share_a_name(conn):
    first = billing.create_customer(conn, "Acme", "one@acme.example")
    second = billing.create_customer(conn, "Acme", "two@acme.example")
    assert first["id"] != second["id"]


def test_unknown_customer_is_rejected(conn):
    with pytest.raises(BillingError):
        billing.create_subscription(conn, 999, 1)


# --------------------------------------------------------------------- plans
def test_publishing_an_existing_name_creates_a_new_version(conn):
    v1 = billing.create_plan(conn, "Starter", 1000)
    v2 = billing.create_plan(conn, "Starter", 1500)
    assert (v1["version"], v2["version"]) == (1, 2)
    assert conn.execute("SELECT archived FROM plans WHERE id = ?", (v1["id"],)).fetchone()["archived"] == 1
    assert [p["version"] for p in billing.list_plans(conn)] == [2]
    assert [p["version"] for p in billing.list_plans(conn, include_archived=True)] == [1, 2]


def test_plan_validation(conn):
    with pytest.raises(BillingError):
        billing.create_plan(conn, "", 100)
    with pytest.raises(BillingError):
        billing.create_plan(conn, "P", 100, interval="week")
    with pytest.raises(BillingError):
        billing.create_plan(conn, "P", 100, currency="EURO")


def test_resolve_plan_by_name_picks_the_newest_version(conn):
    billing.create_plan(conn, "Starter", 1000)
    billing.create_plan(conn, "Starter", 1500)
    assert billing.resolve_plan(conn, "Starter")["version"] == 2
    with pytest.raises(BillingError):
        billing.resolve_plan(conn, "Nope")


def test_subscribing_to_an_archived_version_fails(conn):
    old = billing.create_plan(conn, "Starter", 1000)
    billing.create_plan(conn, "Starter", 1500)
    customer = billing.create_customer(conn, "Acme", None)
    with pytest.raises(BillingError):
        billing.create_subscription(conn, customer["id"], old["id"])


# ------------------------------------------------------------- subscriptions
def test_active_subscription_issues_an_invoice(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    sub = billing.create_subscription(conn, customer["id"], plan["id"], "active", "2025-12-02")
    invoices = billing.invoice_rows(conn, sub["id"])
    assert len(invoices) == 1
    assert invoices[0]["amount_cents"] == 7000
    assert invoices[0]["period_start"] == "2025-12-02"
    assert invoices[0]["period_end"] == "2026-01-01"
    assert invoices[0]["status"] == "open"


def test_pending_subscription_issues_no_invoice(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    sub = billing.create_subscription(conn, customer["id"], plan["id"], "pending", "2025-12-02")
    assert billing.invoice_rows(conn, sub["id"]) == []


def test_mrr_counts_only_active_subscriptions(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    billing.create_subscription(conn, customer["id"], plan["id"], "active")
    billing.create_subscription(conn, customer["id"], plan["id"], "pending")
    assert billing.summary(conn)["mrr_cents"] == 7000


def test_mrr_mixes_monthly_and_yearly_plans(conn):
    customer = billing.create_customer(conn, "Acme", None)
    monthly = billing.create_plan(conn, "Monthly", 7000, interval="month")
    yearly = billing.create_plan(conn, "Yearly", 120000, interval="year")
    billing.create_subscription(conn, customer["id"], monthly["id"], "active")
    billing.create_subscription(conn, customer["id"], yearly["id"], "active")
    assert billing.summary(conn)["mrr_cents"] == 7000 + 10000


def test_existing_subscription_keeps_its_version_and_price(conn):
    customer = billing.create_customer(conn, "Acme", None)
    v1 = billing.create_plan(conn, "Starter", 1000)
    sub = billing.create_subscription(conn, customer["id"], v1["id"], "active")
    billing.create_plan(conn, "Starter", 2500)  # price rise -> version 2
    rows = billing.subscription_rows(conn)
    assert len(rows) == 1
    assert rows[0]["id"] == sub["id"]
    assert rows[0]["plan_version"] == 1
    assert rows[0]["mrr_cents"] == 1000  # grandfathered


def test_only_a_pending_subscription_can_be_activated(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    active = billing.create_subscription(conn, customer["id"], plan["id"], "active")
    with pytest.raises(BillingError):
        billing.activate_subscription(conn, active["id"])


def test_activating_a_pending_subscription_issues_the_first_invoice(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    sub = billing.create_subscription(conn, customer["id"], plan["id"], "pending", "2025-12-02")
    billing.activate_subscription(conn, sub["id"])
    updated = billing.get_subscription(conn, sub["id"])
    assert updated["status"] == "active"
    assert len(billing.invoice_rows(conn, sub["id"])) == 1


def test_cancelling_sets_the_end_date_and_voids_open_invoices(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    sub = billing.create_subscription(conn, customer["id"], plan["id"], "active", "2025-01-01")
    billing.cancel_subscription(conn, sub["id"], "2025-06-30")
    updated = billing.get_subscription(conn, sub["id"])
    assert updated["status"] == "canceled"
    assert updated["end_date"] == "2025-06-30"
    assert [i["status"] for i in billing.invoice_rows(conn, sub["id"])] == ["void"]
    assert billing.summary(conn)["mrr_cents"] == 0


def test_cancelling_twice_is_rejected(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    sub = billing.create_subscription(conn, customer["id"], plan["id"], "active", "2025-01-01")
    billing.cancel_subscription(conn, sub["id"], "2025-06-30")
    with pytest.raises(BillingError):
        billing.cancel_subscription(conn, sub["id"], "2025-07-01")


def test_end_date_before_start_date_is_rejected(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    sub = billing.create_subscription(conn, customer["id"], plan["id"], "active", "2025-06-01")
    with pytest.raises(BillingError):
        billing.cancel_subscription(conn, sub["id"], "2025-05-01")


def test_invalid_initial_status_is_rejected(conn):
    customer = billing.create_customer(conn, "Acme", None)
    plan = billing.create_plan(conn, "Starter", 7000)
    with pytest.raises(BillingError):
        billing.create_subscription(conn, customer["id"], plan["id"], "canceled")


# --------------------------------------------------------------- searching
def test_search_matches_customer_or_plan_case_insensitively(seeded):
    by_customer = billing.subscription_rows(seeded, q="pulse")
    by_plan = billing.subscription_rows(seeded, q="ENTERPRISE")
    assert by_customer and all("Pulse" in r["customer_name"] for r in by_customer)
    assert [r["plan_name"] for r in by_plan] == ["Enterprise Platform"]
    assert billing.subscription_rows(seeded, q="zzz-nothing") == []


def test_status_filter(seeded):
    pending = billing.subscription_rows(seeded, status="pending")
    assert pending and all(r["status"] == "pending" for r in pending)
    with pytest.raises(BillingError):
        billing.subscription_rows(seeded, status="nonsense")


def test_invoice_numbers_are_unique_and_sequential(seeded):
    numbers = [i["number"] for i in billing.invoice_rows(seeded)]
    assert len(numbers) == len(set(numbers))
    assert sorted(numbers) == sorted(f"INV-{n:06d}" for n in range(1, len(numbers) + 1))
