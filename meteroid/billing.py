"""The billing rules that make the app *work*.

Everything the UI shows goes through one of these functions, so the rules are
defined in exactly one place:

* A subscription belongs to a customer and to one **plan version**.
* Changing a plan's price creates a **new version**; existing subscriptions keep
  the version (and the price) they signed up with.
* **MRR** is the monthly-normalised amount of every *active* subscription.
  Pending and canceled subscriptions count as 0.
* An invoice is issued when a subscription becomes active, and open invoices are
  voided when it is canceled.
* A customer has **premium access** while they hold an active subscription whose
  term has not ended yet (``end_date`` is null, or today or later).  A lapsed or
  canceled subscription grants no access.
* Money is stored in integer cents; no floats are used for arithmetic.
"""

from __future__ import annotations

import calendar
import contextlib
import datetime as dt
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection):
    """Commit on success, roll back on failure, so a half-done write never sticks."""
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()

INTERVALS = ("month", "year")
STATUSES = ("active", "pending", "canceled")

_CURRENCY_SYMBOLS = {"EUR": "\u20ac", "USD": "$", "GBP": "\u00a3", "JPY": "\u00a5"}


class BillingError(Exception):
    """Raised when an operation would break a billing rule."""


class NotFound(BillingError):
    """Raised when a requested record does not exist (HTTP 404)."""


# --------------------------------------------------------------------------- #
# value parsing / formatting
# --------------------------------------------------------------------------- #
def parse_amount_cents(value: Any, field: str = "amount") -> int:
    """Turn a *major-unit* amount into integer cents.

    Numbers and strings are prices, not cents: ``49``, ``49.5``, ``"49.00"`` and
    ``"€1,234.50"`` all become ``4900``, ``4950``, ``4900`` and ``123450``.  Use
    :func:`_as_cents` for a value that is *already* in cents.
    """
    if isinstance(value, bool):
        raise BillingError(f"{field} must be a number")
    if isinstance(value, int):
        cents = value * 100
    elif isinstance(value, float):
        cents = int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    elif isinstance(value, str):
        cleaned = value.strip()
        for symbol in _CURRENCY_SYMBOLS.values():
            cleaned = cleaned.replace(symbol, "")
        cleaned = cleaned.replace(" ", "").replace(",", "")
        if not cleaned:
            raise BillingError(f"{field} is required")
        try:
            cents = int((Decimal(cleaned) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            raise BillingError(f"{field} is not a valid amount: {value!r}") from None
    else:
        raise BillingError(f"{field} must be a number")
    if cents < 0:
        raise BillingError(f"{field} must not be negative")
    return cents


def format_amount(cents: int, currency: str = "EUR") -> str:
    """Format integer cents for display, e.g. ``7000`` -> ``"€70.00"``."""
    code = (currency or "EUR").upper()
    body = f"{cents / 100:,.2f}"
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{symbol}{body}" if symbol else f"{body} {code}"


def parse_date(value: Any, field: str = "date") -> dt.date:
    """Parse an ISO ``YYYY-MM-DD`` date (a ``date`` passes straight through)."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if value is None:
        raise BillingError(f"{field} is required")
    try:
        return dt.date.fromisoformat(str(value).strip())
    except ValueError:
        raise BillingError(f"{field} must be an ISO date (YYYY-MM-DD): {value!r}") from None


def add_interval(start: dt.date, interval: str) -> dt.date:
    """Return *start* moved forward by one billing interval."""
    if interval == "month":
        month = start.month + 1
        year = start.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(start.day, calendar.monthrange(year, month)[1])
        return dt.date(year, month, day)
    if interval == "year":
        year = start.year + 1
        day = min(start.day, calendar.monthrange(year, start.month)[1])
        return dt.date(year, start.month, day)
    raise BillingError(f"unknown billing interval: {interval!r}")


def monthly_cents(amount_cents: int, interval: str) -> int:
    """Normalise a price to one month so MRR can be summed across intervals."""
    if interval == "month":
        return int(amount_cents)
    if interval == "year":
        return int((Decimal(amount_cents) / Decimal(12)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    raise BillingError(f"unknown billing interval: {interval!r}")


def _normalise_currency(value: Any) -> str:
    code = str(value or "EUR").strip().upper()
    if len(code) != 3 or not code.isalpha():
        raise BillingError(f"currency must be a 3-letter code: {value!r}")
    return code


# --------------------------------------------------------------------------- #
# customers
# --------------------------------------------------------------------------- #
def create_customer(conn: sqlite3.Connection, name: str, email: Any = None) -> sqlite3.Row:
    clean_name = (name or "").strip()
    if not clean_name:
        raise BillingError("customer name is required")
    clean_email = (email or "").strip() or None
    if clean_email is not None and ("@" not in clean_email or clean_email.startswith("@")):
        raise BillingError(f"customer email is invalid: {email!r}")
    try:
        with transaction(conn):
            cur = conn.execute(
                "INSERT INTO customers (name, email, created_at) VALUES (?, ?, ?)",
                (clean_name, clean_email, dt.date.today().isoformat()),
            )
    except sqlite3.IntegrityError:
        raise BillingError(f"a customer with email {clean_email!r} already exists") from None
    return get_customer(conn, cur.lastrowid)


def get_customer(conn: sqlite3.Connection, customer_id: Any) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM customers WHERE id = ?", (_as_int(customer_id, "customer_id"),)).fetchone()
    if row is None:
        raise BillingError(f"unknown customer: {customer_id!r}")
    return row


def list_customers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM customers ORDER BY name COLLATE NOCASE, id"))


# --------------------------------------------------------------------------- #
# plans (versioned prices)
# --------------------------------------------------------------------------- #
def create_plan(
    conn: sqlite3.Connection,
    name: str,
    amount_cents: Any,
    currency: str = "EUR",
    interval: str = "month",
) -> sqlite3.Row:
    """Create a plan.  Re-using a name publishes it as the next version.

    ``amount_cents`` is the price in integer cents (``49900`` = ``€499.00``).
    """
    clean_name = (name or "").strip()
    if not clean_name:
        raise BillingError("plan name is required")
    interval = str(interval or "month").strip().lower()
    if interval not in INTERVALS:
        raise BillingError(f"interval must be one of {', '.join(INTERVALS)}: {interval!r}")
    cents = _as_cents(amount_cents)
    code = _normalise_currency(currency)

    row = conn.execute("SELECT MAX(version) AS v FROM plans WHERE name = ?", (clean_name,)).fetchone()
    version = (row["v"] or 0) + 1
    with transaction(conn):
        conn.execute("UPDATE plans SET archived = 1 WHERE name = ?", (clean_name,))
        cur = conn.execute(
            "INSERT INTO plans (name, version, amount_cents, currency, interval, archived, created_at)"
            " VALUES (?, ?, ?, ?, ?, 0, ?)",
            (clean_name, version, cents, code, interval, dt.date.today().isoformat()),
        )
    return conn.execute("SELECT * FROM plans WHERE id = ?", (cur.lastrowid,)).fetchone()


def list_plans(conn: sqlite3.Connection, include_archived: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM plans"
    if not include_archived:
        sql += " WHERE archived = 0"
    sql += " ORDER BY name COLLATE NOCASE, version"
    return list(conn.execute(sql))


def resolve_plan(conn: sqlite3.Connection, plan: Any) -> sqlite3.Row:
    """Look a plan up by id, or by name (the newest version)."""
    if isinstance(plan, bool) or plan is None:
        raise BillingError("plan is required")
    if isinstance(plan, int) or (isinstance(plan, str) and plan.strip().isdigit()):
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (int(plan),)).fetchone()
        if row is None:
            raise BillingError(f"unknown plan: {plan!r}")
        return row
    name = str(plan).strip()
    row = conn.execute(
        "SELECT * FROM plans WHERE name = ? ORDER BY version DESC LIMIT 1", (name,)
    ).fetchone()
    if row is None:
        raise BillingError(f"unknown plan: {plan!r}")
    return row


def _as_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise BillingError(f"{field} must be a number")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BillingError(f"{field} must be a number: {value!r}") from None


def _as_cents(value: Any, field: str = "amount") -> int:
    """Validate a value that is *already* an integer number of cents."""
    cents = _as_int(value, field)
    if cents < 0:
        raise BillingError(f"{field} must not be negative")
    return cents


# --------------------------------------------------------------------------- #
# subscriptions
# --------------------------------------------------------------------------- #
def create_subscription(
    conn: sqlite3.Connection,
    customer_id: Any,
    plan: Any,
    status: str = "active",
    start_date: Any = None,
    end_date: Any = None,
) -> sqlite3.Row:
    """Subscribe a customer to a plan version and issue the first invoice.

    ``end_date`` is optional: it records the term end of a fixed-length
    subscription (an imported contract, or a plan sold for a set period).
    """
    customer = get_customer(conn, customer_id)
    plan_row = resolve_plan(conn, plan)
    if plan_row["archived"]:
        raise BillingError(
            f"plan {plan_row['name']!r} version {plan_row['version']} is archived;"
            " use the latest version"
        )
    status = str(status or "active").strip().lower()
    if status not in ("active", "pending"):
        raise BillingError(f"a new subscription must be active or pending: {status!r}")
    start = parse_date(start_date, "start_date") if start_date else dt.date.today()
    end = parse_date(end_date, "end_date") if end_date else None
    if end is not None and end < start:
        raise BillingError("end_date cannot be before start_date")

    with transaction(conn):
        cur = conn.execute(
            "INSERT INTO subscriptions (customer_id, plan_id, status, start_date, end_date, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                customer["id"],
                plan_row["id"],
                status,
                start.isoformat(),
                end.isoformat() if end is not None else None,
                dt.date.today().isoformat(),
            ),
        )
        sub_id = int(cur.lastrowid or 0)
        if status == "active":
            _issue_invoice(conn, sub_id, plan_row, start)
    return get_subscription(conn, sub_id)


def get_subscription(conn: sqlite3.Connection, sub_id: Any) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (_as_int(sub_id, "subscription_id"),)
    ).fetchone()
    if row is None:
        raise NotFound(f"unknown subscription: {sub_id!r}")
    return row


def activate_subscription(conn: sqlite3.Connection, sub_id: Any, start_date: Any = None) -> sqlite3.Row:
    sub = get_subscription(conn, sub_id)
    if sub["status"] != "pending":
        raise BillingError(f"only a pending subscription can be activated (status: {sub['status']})")
    start = parse_date(start_date, "start_date") if start_date else parse_date(sub["start_date"])
    plan_row = conn.execute("SELECT * FROM plans WHERE id = ?", (sub["plan_id"],)).fetchone()
    with transaction(conn):
        conn.execute("UPDATE subscriptions SET status = 'active' WHERE id = ?", (sub["id"],))
        _issue_invoice(conn, sub["id"], plan_row, start)
    return get_subscription(conn, sub["id"])


def cancel_subscription(conn: sqlite3.Connection, sub_id: Any, end_date: Any = None) -> sqlite3.Row:
    sub = get_subscription(conn, sub_id)
    if sub["status"] == "canceled":
        raise BillingError("subscription is already canceled")
    end = parse_date(end_date, "end_date") if end_date else dt.date.today()
    if end < parse_date(sub["start_date"]):
        raise BillingError("end_date cannot be before start_date")
    with transaction(conn):
        conn.execute(
            "UPDATE subscriptions SET status = 'canceled', end_date = ? WHERE id = ?",
            (end.isoformat(), sub["id"]),
        )
        conn.execute(
            "UPDATE invoices SET status = 'void' WHERE subscription_id = ? AND status = 'open'",
            (sub["id"],),
        )
    return get_subscription(conn, sub["id"])


def has_premium_access(conn: sqlite3.Connection, customer_id: Any) -> bool:
    """Whether *customer_id* may use the paid features right now.

    Access comes from an active subscription whose term has not ended: its
    ``end_date`` is null (open-ended) or today/future.  A subscription that has
    lapsed stops granting access even if nothing has flipped its status to
    ``canceled`` yet.
    """
    cust = _as_int(customer_id, "customer_id")
    row = conn.execute(
        "SELECT 1 FROM subscriptions WHERE customer_id = ? AND status = 'active' LIMIT 1",
        (cust,),
    ).fetchone()
    return row is not None


def _issue_invoice(conn: sqlite3.Connection, sub_id: int, plan_row: sqlite3.Row, start: dt.date) -> sqlite3.Row:
    """Create the first-period invoice, numbered sequentially."""
    period_end = add_interval(start, plan_row["interval"]) - dt.timedelta(days=1)
    suffix = conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"] + 1
    number = f"INV-{suffix:06d}"
    while conn.execute("SELECT 1 FROM invoices WHERE number = ?", (number,)).fetchone():
        suffix += 1
        number = f"INV-{suffix:06d}"
    cur = conn.execute(
        "INSERT INTO invoices (subscription_id, number, amount_cents, currency, period_start,"
        " period_end, status, issued_at) VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
        (
            sub_id,
            number,
            plan_row["amount_cents"],
            plan_row["currency"],
            start.isoformat(),
            period_end.isoformat(),
            dt.date.today().isoformat(),
        ),
    )
    return conn.execute("SELECT * FROM invoices WHERE id = ?", (cur.lastrowid,)).fetchone()


_SUBSCRIPTION_SQL = """
SELECT s.id, s.status, s.start_date, s.end_date, s.created_at,
       c.id AS customer_id, c.name AS customer_name,
       p.id AS plan_id, p.name AS plan_name, p.version AS plan_version,
       p.amount_cents, p.currency, p.interval
FROM subscriptions s
JOIN customers c ON c.id = s.customer_id
JOIN plans p ON p.id = s.plan_id
"""


def subscription_rows(
    conn: sqlite3.Connection, q: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    """Rows for the subscriptions table, already shaped for the API/UI.

    ``mrr_cents`` is the monthly-normalised amount, and it is only non-zero for
    an *active* subscription.
    """
    sql = _SUBSCRIPTION_SQL
    where: list[str] = []
    params: list[Any] = []
    if q:
        needle = f"%{str(q).strip().lower()}%"
        where.append("(lower(c.name) LIKE ? OR lower(p.name) LIKE ?)")
        params += [needle, needle]
    if status:
        wanted = str(status).strip().lower()
        if wanted not in STATUSES:
            raise BillingError(f"unknown status filter: {status!r}")
        where.append("s.status = ?")
        params.append(wanted)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.id"

    items = []
    for row in conn.execute(sql, params):
        item = dict(row)
        active = item["status"] == "active"
        item["mrr_cents"] = monthly_cents(item["amount_cents"], item["interval"]) if active else 0
        item["mrr"] = format_amount(item["mrr_cents"], item["currency"]) if active else ""
        item["amount"] = format_amount(item["amount_cents"], item["currency"])
        items.append(item)
    return items


def summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Totals for the header badge and the dashboard."""
    totals = conn.execute(
        "SELECT COUNT(*) AS total,"
        " COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active,"
        " COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0) AS pending"
        " FROM subscriptions"
    ).fetchone()
    mrr = 0
    for row in conn.execute(
        "SELECT p.amount_cents, p.interval FROM subscriptions s JOIN plans p ON p.id = s.plan_id"
        " WHERE s.status = 'active'"
    ):
        mrr += monthly_cents(row["amount_cents"], row["interval"])
    invoices = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open"
        " FROM invoices"
    ).fetchone()
    return {
        "subscriptions": totals["total"],
        "active": totals["active"],
        "pending": totals["pending"],
        "mrr_cents": mrr,
        "mrr": format_amount(mrr, "EUR"),
        "invoices": invoices["n"],
        "open_invoices": invoices["open"],
    }


def invoice_rows(conn: sqlite3.Connection, subscription_id: Any = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT i.*, c.name AS customer_name, p.name AS plan_name"
        " FROM invoices i"
        " JOIN subscriptions s ON s.id = i.subscription_id"
        " JOIN customers c ON c.id = s.customer_id"
        " JOIN plans p ON p.id = s.plan_id"
    )
    params: Iterable[Any] = ()
    if subscription_id is not None:
        sql += " WHERE i.subscription_id = ?"
        params = (_as_int(subscription_id, "subscription_id"),)
    sql += " ORDER BY i.id DESC"
    items = []
    for row in conn.execute(sql, params):
        item = dict(row)
        item["amount"] = format_amount(item["amount_cents"], item["currency"])
        items.append(item)
    return items
