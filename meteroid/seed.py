"""Demo data so the app has something to show on first run.

The customers and plans mirror the design mock-up this UI is based on.  The
seed exercises plan versioning the way real history does: subscriptions are
created while their plan version is current, and later versions are published
afterwards - so an *existing* subscription can still sit on version 4 while the
catalogue has moved on to version 5.
"""

from __future__ import annotations

import sqlite3

from . import billing

CUSTOMERS = [
    ("Cobalt Industries SAS", "billing@cobalt-industries.example"),
    ("Pulse Analytics GmbH", "billing@pulse-analytics.example"),
    ("Evergreen Dynamics Ltd", "billing@evergreen-dynamics.example"),
]


def _latest_plan_id(conn: sqlite3.Connection, name: str) -> int:
    return conn.execute("SELECT id FROM plans WHERE name = ? ORDER BY version DESC LIMIT 1", (name,)).fetchone()["id"]


def seed_demo(conn: sqlite3.Connection) -> bool:
    """Insert the demo data.  Returns ``False`` if the database is not empty."""
    if conn.execute("SELECT COUNT(*) AS n FROM subscriptions").fetchone()["n"]:
        return False

    customer_ids = {name: billing.create_customer(conn, name, email)["id"] for name, email in CUSTOMERS}

    def subscribe(customer: str, plan: str, status: str, start: str, end: str | None = None) -> None:
        billing.create_subscription(
            conn, customer_ids[customer], _latest_plan_id(conn, plan), status, start, end
        )

    # Version 1 of every plan.
    billing.create_plan(conn, "Enterprise Platform", 49900, "EUR", "month")
    billing.create_plan(conn, "Standard 80", 8000, "EUR", "month")
    billing.create_plan(conn, "Standard 20", 2000, "EUR", "month")
    for amount in (5000, 7000, 7000, 7000):  # "test" versions 1..4
        billing.create_plan(conn, "test", amount, "EUR", "month")

    # Subscriptions taken out while those versions were the current ones.
    subscribe("Pulse Analytics GmbH", "Enterprise Platform", "active", "2025-09-01")
    subscribe("Pulse Analytics GmbH", "Standard 80", "active", "2025-11-18")
    subscribe("Pulse Analytics GmbH", "Standard 20", "pending", "2025-12-02")
    subscribe("Pulse Analytics GmbH", "test", "pending", "2025-11-27")
    subscribe("Pulse Analytics GmbH", "test", "active", "2025-10-01")
    subscribe("Evergreen Dynamics Ltd", "test", "active", "2025-10-01", "2026-03-31")

    # Publish the next versions, then the subscriptions that use them.
    billing.create_plan(conn, "test", 7000, "EUR", "month")  # version 5
    billing.create_plan(conn, "Annual Boost", 120000, "EUR", "year")
    # Cobalt and Evergreen stopped renewing: their fixed terms ended, but no
    # reconciliation job has moved the subscriptions off "active" yet.
    subscribe("Cobalt Industries SAS", "test", "active", "2025-12-02", "2026-03-31")
    subscribe("Evergreen Dynamics Ltd", "test", "active", "2025-10-01", "2026-03-31")
    subscribe("Cobalt Industries SAS", "test", "active", "2025-12-01", "2026-03-31")
    subscribe("Evergreen Dynamics Ltd", "Annual Boost", "active", "2025-10-01", "2026-09-30")
    return True
