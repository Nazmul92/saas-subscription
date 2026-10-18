# Meteroid

A small SaaS subscription-billing app — customers, plans, subscriptions and
invoices — built on Python's standard library (`sqlite3` + `wsgiref`) with a
vanilla-JS UI. No framework, no third-party dependencies.

## Quick start

```bash
python server.py            # http://127.0.0.1:8000
python server.py --port 9000
python server.py --reset    # delete the database and re-seed the demo data
```

Environment variables: `METEROID_DB` (database file), `PORT`.

The database file is created on first run and seeded with three demo customers:
Pulse Analytics GmbH, Cobalt Industries SAS and Evergreen Dynamics Ltd.

## What it does

- **Plans** are versioned. Editing a plan publishes a new version instead of
  mutating the old one, so existing subscriptions keep the price they signed up
  for. Archived versions cannot be subscribed to.
- **Subscriptions** move through `pending` → `active` → `canceled`. A new
  subscription issues its first invoice. A fixed-length subscription can carry
  an `end_date` recording when its term ends.
- **Invoices** record integer cents; open invoices are voided when a
  subscription is canceled.
- **Premium access** is what the paid features hang off. The rule:

  > A customer has premium access **only while they hold an active subscription
  > whose term has not ended** — its `end_date` is null (open-ended), or today or
  > later. A lapsed or canceled subscription grants no access.

  The Customers page shows this as the "Premium access" column, and
  `GET /api/customers` exposes it as the `premium` boolean.

## API

```
GET  /api/summary                        totals + MRR for the header/dashboard
GET  /api/customers                      list customers (with `premium` access)
POST /api/customers                      create a customer
GET  /api/plans                          list plan versions
POST /api/plans                          create a plan / publish a new version
GET  /api/subscriptions                  table rows (`?q=` and `?status=`)
POST /api/subscriptions                  subscribe a customer to a plan
GET  /api/subscriptions/<id>             one subscription
POST /api/subscriptions/<id>/activate    pending -> active
POST /api/subscriptions/<id>/cancel      activate -> canceled
GET  /api/invoices                       invoices (`?subscription_id=`)
```

## Tests

```bash
python -m pytest -q
```

The suite runs against a temporary database; nothing here touches your working
database file. `tests/test_spec_entitlement.py` pins the premium-access rule
above; the money, API and frontend specs pin the rest.

## Layout

```
server.py              WSGI entry point (bootstrap + serve)
meteroid/
  db.py                connection handling + schema
  billing.py           domain logic (plans, subscriptions, invoices, access)
  api.py               JSON API + static file serving
  seed.py              demo data
static/                index.html, app.js, styles.css
tests/                 pytest suite
```
