"""End-to-end tests over real HTTP, plus the static frontend files."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"


def make_customer(client, name="Acme Ltd", email="billing@acme.example"):
    status, body = client.post("/api/customers", {"name": name, "email": email})
    assert status == 201, body
    return body


def make_plan(client, name="Starter", amount="49.00", **extra):
    payload = {"name": name, "amount": amount, **extra}
    status, body = client.post("/api/plans", payload)
    assert status == 201, body
    return body


# ------------------------------------------------------------------- health
def test_server_survives_an_empty_database(client):
    for path in ("/api/summary", "/api/subscriptions", "/api/customers", "/api/plans", "/api/invoices"):
        status, body = client.get(path)
        assert status == 200, (path, body)
    assert client.get("/api/subscriptions")[1]["items"] == []
    assert client.get("/api/summary")[1]["mrr_cents"] == 0


def test_unknown_route_is_a_404(client):
    status, body = client.get("/api/nope")
    assert status == 404
    assert "error" in body


# --------------------------------------------------------------- the frontend
def test_index_html_is_served(client):
    status, _ = client.get("/api/summary")
    assert status == 200
    import urllib.request

    with urllib.request.urlopen(client.base + "/", timeout=10) as res:
        html = res.read().decode()
    assert res.status == 200
    assert "Subscriptions" in html and "app.js" in html


def test_frontend_assets_exist_and_wire_up_the_columns():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")

    # The table columns from the design mock-up.
    for column in ["Customer", "Plan", "Version", "MRR", "Start date", "End date", "Status", "Currency"]:
        assert f"<th>{column}</th>" in js, column

    # Every navigation entry from the mock-up is present.
    for label in ["Home", "Product catalog", "Metrics", "Coupons", "Addons", "Features", "Billing",
                  "Subscriptions", "Invoices", "Credit notes", "Customers", "Help & Feedback",
                  "Settings", "Developers"]:
        assert f"label: '{label}'" in js, label

    # The accent colours sampled from the mock-up.
    assert "#4fbf9b" in css
    assert "#f59e0b" in css
    assert "--bg: #121212" in css
    assert re.search(r'id="page-count"', html)


def test_frontend_calls_the_real_api():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for endpoint in ["/api/subscriptions", "/api/summary", "/api/customers", "/api/plans", "/api/invoices"]:
        assert endpoint in js, endpoint


# ------------------------------------------------------- customer/plan flow
def test_create_customer_and_plan_then_subscription(client):
    customer = make_customer(client)
    plan = make_plan(client, amount="70.00")

    status, sub = client.post("/api/subscriptions", {
        "customer_id": customer["id"], "plan_id": plan["id"], "start_date": "2025-12-02",
    })
    assert status == 201, sub
    assert sub["customer"] == "Acme Ltd"
    assert sub["plan"] == "Starter"
    assert sub["status"] == "active"
    assert sub["mrr"] == "\u20ac70.00"
    assert sub["currency"] == "EUR"

    table = client.get("/api/subscriptions")[1]
    assert table["count"] == 1 and table["total"] == 1
    assert table["items"][0]["version"] == 1
    assert table["items"][0]["start_date"] == "2025-12-02"


def test_subscription_requires_an_existing_customer_and_plan(client):
    plan = make_plan(client)
    status, body = client.post("/api/subscriptions", {"customer_id": 999, "plan_id": plan["id"]})
    assert status == 400
    assert "customer" in body["error"]

    customer = make_customer(client)
    status, body = client.post("/api/subscriptions", {"customer_id": customer["id"], "plan_id": 999})
    assert status == 400
    assert "plan" in body["error"]


def test_a_failed_create_leaves_no_subscription_behind(client):
    customer = make_customer(client)
    client.post("/api/subscriptions", {"customer_id": customer["id"], "plan_id": 999})
    assert client.get("/api/subscriptions")[1]["total"] == 0


def test_bad_payloads_are_rejected_with_a_message(client):
    cases = [
        ("/api/customers", {"name": ""}),
        ("/api/plans", {"name": "P", "amount": "abc"}),
        ("/api/plans", {"name": "P", "amount": "-1"}),
        ("/api/plans", {"name": "P", "amount": "1", "interval": "week"}),
    ]
    for path, payload in cases:
        status, body = client.post(path, payload)
        assert status == 400, (path, payload, body)
        assert body.get("error")


def test_malformed_json_is_a_400(client):
    import urllib.request
    import urllib.error

    req = urllib.request.Request(client.base + "/api/customers", data=b"{not json",
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("expected a 400")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_search_and_count_endpoint(client):
    c1 = make_customer(client, "Cobalt Industries SAS", "a@cobalt.example")
    c2 = make_customer(client, "Pulse Analytics GmbH", "b@pulse.example")
    plan = make_plan(client, "Enterprise Platform")

    for customer in (c1, c2):
        client.post("/api/subscriptions", {"customer_id": customer["id"], "plan_id": plan["id"]})

    body = client.get("/api/subscriptions?q=pulse")[1]
    assert body["count"] == 1
    assert body["total"] == 2
    assert body["items"][0]["customer"] == "Pulse Analytics GmbH"

    assert client.get("/api/subscriptions?q=enterprise")[1]["count"] == 2
    assert client.get("/api/subscriptions?q=zzz")[1]["count"] == 0


def test_activation_and_cancellation_over_http(client):
    customer = make_customer(client)
    plan = make_plan(client)
    pending = client.post("/api/subscriptions", {
        "customer_id": customer["id"], "plan_id": plan["id"], "status": "pending",
        "start_date": "2025-12-02",
    })[1]
    assert pending["status"] == "pending"
    assert client.get("/api/summary")[1]["mrr_cents"] == 0

    status, activated = client.post(f"/api/subscriptions/{pending['id']}/activate")
    assert status == 200 and activated["status"] == "active"
    assert len(activated["invoices"]) == 1
    assert client.get("/api/summary")[1]["mrr"] == "\u20ac49.00"

    status, canceled = client.post(f"/api/subscriptions/{pending['id']}/cancel", {"end_date": "2026-01-31"})
    assert status == 200 and canceled["status"] == "canceled"
    assert canceled["end_date"] == "2026-01-31"
    assert [i["status"] for i in canceled["invoices"]] == ["void"]
    assert client.get("/api/summary")[1]["mrr_cents"] == 0

    status, body = client.post(f"/api/subscriptions/{pending['id']}/cancel")
    assert status == 400 and body["error"]


def test_missing_subscription_is_a_404(client):
    assert client.get("/api/subscriptions/1234")[0] == 404
    assert client.post("/api/subscriptions/1234/cancel")[0] == 404
    assert client.post("/api/subscriptions/1234/activate")[0] == 404


def test_plan_catalogue_lists_versions(client):
    make_plan(client, "Starter", "10.00")
    make_plan(client, "Starter", "15.00")
    latest = client.get("/api/plans")[1]["items"]
    assert [(p["name"], p["version"]) for p in latest] == [("Starter", 2)]
    all_versions = client.get("/api/plans?include_archived=1")[1]["items"]
    assert [(p["name"], p["version"]) for p in all_versions] == [("Starter", 1), ("Starter", 2)]


def test_seeded_data_matches_the_mockup_customers(client_with_seed):
    body = client_with_seed.get("/api/subscriptions")[1]
    assert body["total"] == 10
    names = {r["customer"] for r in body["items"]}
    assert names == {"Cobalt Industries SAS", "Pulse Analytics GmbH", "Evergreen Dynamics Ltd"}
    assert {r["currency"] for r in body["items"]} == {"EUR"}
    assert {r["status"] for r in body["items"]} == {"active", "pending"}


@pytest.fixture
def client_with_seed(db_file):
    import threading
    import urllib.error
    import urllib.request
    from wsgiref.simple_server import make_server

    from server import ThreadingWSGIServer, bootstrap

    app = bootstrap(db_file, reset=True, seed=True)
    httpd = make_server("127.0.0.1", 0, app, server_class=ThreadingWSGIServer)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    from conftest import Client  # pyright: ignore[reportImplicitRelativeImport]

    try:
        yield Client(f"http://127.0.0.1:{httpd.server_address[1]}")
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
