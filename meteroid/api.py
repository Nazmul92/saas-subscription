"""WSGI HTTP API + static file server for Meteroid.

The app is a plain WSGI callable, so it can be served by ``wsgiref`` in
``server.py`` or called directly from tests without opening a socket.

Routes
------
``GET  /api/summary``                        totals + MRR for the header/dashboard
``GET  /api/customers``                      list customers (with ``premium`` access)
``POST /api/customers``                      create a customer
``GET  /api/plans``                          list plan versions
``POST /api/plans``                          create a plan / publish a new version
``GET  /api/subscriptions``                  table rows (``?q=`` and ``?status=``)
``POST /api/subscriptions``                  subscribe a customer to a plan
``GET  /api/subscriptions/<id>``             one subscription
``POST /api/subscriptions/<id>/activate``    pending -> active
``POST /api/subscriptions/<id>/cancel``      activate -> canceled
``GET  /api/invoices``                       invoices (``?subscription_id=``)
"""

from __future__ import annotations

import json
import mimetypes
import re
import sqlite3
import traceback
from pathlib import Path
from typing import Any, Callable, Iterable

from . import billing
from .db import open_db

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_ROUTE = re.compile(r"^/api/subscriptions/(?P<id>\d+)(?:/(?P<action>activate|cancel))?$")


class App:
    """A WSGI application bound to a SQLite database path (or connection)."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path

    # -- helpers ----------------------------------------------------------- #
    def _conn(self) -> sqlite3.Connection:
        return open_db(self.db_path)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/") or "/"

        if not path.startswith("/api/"):
            return self._static(path, start_response)

        conn = self._conn()
        try:
            status, payload = self._dispatch(conn, method, path, environ)
        except billing.NotFound as exc:
            status, payload = 404, {"error": str(exc)}
        except billing.BillingError as exc:
            status, payload = 400, {"error": str(exc)}
        except Exception:  # pragma: no cover - defensive
            traceback.print_exc()
            status, payload = 500, {"error": "internal server error"}
        finally:
            conn.close()

        body = json.dumps(payload).encode("utf-8")
        start_response(
            f"{status} {_reason(status)}",
            [("Content-Type", "application/json; charset=utf-8"),
             ("Content-Length", str(len(body))),
             ("Cache-Control", "no-store")],
        )
        return [body]

    # -- routing ----------------------------------------------------------- #
    def _dispatch(
        self, conn: sqlite3.Connection, method: str, path: str, environ: dict[str, Any]
    ) -> tuple[int, Any]:
        body = _read_json(environ)

        if path == "/api/summary" and method == "GET":
            return 200, billing.summary(conn)

        if path == "/api/customers":
            if method == "GET":
                items = []
                for row in billing.list_customers(conn):
                    item = dict(row)
                    item["premium"] = billing.has_premium_access(conn, item["id"])
                    items.append(item)
                return 200, {"items": items}
            if method == "POST":
                row = billing.create_customer(conn, _text(body.get("name")), body.get("email"))
                return 201, dict(row)

        if path == "/api/plans":
            if method == "GET":
                include = _truthy(_first(environ, "include_archived"))
                rows = billing.list_plans(conn, include_archived=include)
                return 200, {"items": [_plan_payload(r) for r in rows]}
            if method == "POST":
                if body.get("amount_cents") is not None:
                    cents = body["amount_cents"]
                else:
                    cents = billing.parse_amount_cents(body.get("amount"), "amount")
                row = billing.create_plan(
                    conn,
                    _text(body.get("name")),
                    cents,
                    body.get("currency", "EUR"),
                    body.get("interval", "month"),
                )
                return 201, _plan_payload(row)

        if path == "/api/subscriptions":
            if method == "GET":
                q = _first(environ, "q")
                status = _first(environ, "status")
                items = billing.subscription_rows(conn, q=q, status=status)
                return 200, {
                    "items": [_subscription_payload(i) for i in items],
                    "count": len(items),
                    "total": billing.summary(conn)["subscriptions"],
                }
            if method == "POST":
                row = billing.create_subscription(
                    conn,
                    body.get("customer_id"),
                    body.get("plan_id", body.get("plan")),
                    body.get("status", "active"),
                    body.get("start_date"),
                    body.get("end_date"),
                )
                return 201, self._subscription(conn, row["id"])

        match = _ROUTE.match(path)
        if match:
            sub_id = int(match.group("id"))
            action = match.group("action")
            if action is None and method == "GET":
                return 200, self._subscription(conn, sub_id)
            if action == "activate" and method == "POST":
                billing.activate_subscription(conn, sub_id, body.get("start_date"))
                return 200, self._subscription(conn, sub_id)
            if action == "cancel" and method == "POST":
                billing.cancel_subscription(conn, sub_id, body.get("end_date"))
                return 200, self._subscription(conn, sub_id)

        if path == "/api/invoices" and method == "GET":
            sub_id = _first(environ, "subscription_id")
            return 200, {"items": billing.invoice_rows(conn, sub_id)}

        return 404, {"error": f"no route for {method} {path}"}

    def _subscription(self, conn: sqlite3.Connection, sub_id: int) -> dict[str, Any]:
        row = billing.get_subscription(conn, sub_id)
        rows = [i for i in billing.subscription_rows(conn) if i["id"] == row["id"]]
        payload = _subscription_payload(rows[0])
        payload["invoices"] = billing.invoice_rows(conn, row["id"])
        return payload

    # -- static files ------------------------------------------------------ #
    def _static(self, path: str, start_response: Callable[..., Any]) -> Iterable[bytes]:
        if path in ("/", ""):
            path = "/index.html"
        target = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in target.parents and target != STATIC_DIR:
            return _not_found(start_response)
        if not target.is_file():
            return _not_found(start_response)
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
            mime += "; charset=utf-8"
        body = target.read_bytes()
        start_response(
            "200 OK",
            [("Content-Type", mime), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")],
        )
        return [body]


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _plan_payload(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["archived"] = bool(item["archived"])
    item["amount"] = billing.format_amount(item["amount_cents"], item["currency"])
    item["monthly_cents"] = billing.monthly_cents(item["amount_cents"], item["interval"])
    return item


def _subscription_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Public shape of a subscription row (dates are ISO strings)."""
    return {
        "id": item["id"],
        "customer_id": item["customer_id"],
        "customer": item["customer_name"],
        "plan_id": item["plan_id"],
        "plan": item["plan_name"],
        "version": item["plan_version"],
        "amount_cents": item["amount_cents"],
        "amount": item["amount"],
        "mrr_cents": item["mrr_cents"],
        "mrr": item["mrr"],
        "currency": item["currency"],
        "interval": item["interval"],
        "status": item["status"],
        "start_date": item["start_date"],
        "end_date": item["end_date"],
    }


def _read_json(environ: dict[str, Any]) -> dict[str, Any]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0:
        return {}
    raw = environ["wsgi.input"].read(length)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise billing.BillingError("request body must be valid JSON") from None
    if not isinstance(data, dict):
        raise billing.BillingError("request body must be a JSON object")
    return data


def _first(environ: dict[str, Any], key: str) -> Any:
    from urllib.parse import parse_qs

    values = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    return values.get(key, [None])[0]


def _text(value: Any) -> str:
    """Coerce a JSON field to text, mapping a missing value to ``""``.

    ``billing`` validates the content, so an empty string still becomes a clear
    "… is required" error rather than a 500.
    """
    return value if isinstance(value, str) else ""


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _reason(status: int) -> str:
    return {200: "OK", 201: "Created", 400: "Bad Request", 404: "Not Found", 500: "Internal Server Error"}.get(
        status, "OK"
    )


def _not_found(start_response: Callable[..., Any]) -> Iterable[bytes]:
    body = b"Not found"
    start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def create_app(db_path: str | None = None) -> App:
    """Application factory used by ``server.py`` and the tests."""
    return App(db_path)
