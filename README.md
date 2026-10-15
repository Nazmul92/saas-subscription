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

## Demo: the expired-subscription bug

This repository also doubles as a demo of an agent finding and fixing a real
bug. **It currently ships with one deliberate bug**, so the test suite is red on
purpose: `python -m pytest -q` reports **9 failed, 75 passed**, all nine in
`tests/test_spec_entitlement.py`.

A subscription whose term has ended still grants premium access. In the seeded
data, Cobalt Industries SAS and Evergreen Dynamics Ltd keep the **Premium**
badge even though their subscriptions ended on 2026-03-31 and 2026-09-30. The
cause sits in `meteroid/billing.py`: `has_premium_access` checks only
`status = 'active'` and never looks at `end_date` — its own docstring states the
correct rule, so the code contradicts its contract. The bug applies uniformly to
every customer; there is no per-customer list anywhere.

The fix is one clause:

```sql
AND (end_date IS NULL OR end_date >= ?)
```

With that restored the suite is 84 passed, and the two lapsed customers flip to
"No access" while Pulse Analytics GmbH stays "Premium".

### Story beats (~3 minutes)

1. **The product (0:00–0:20).** Dashboard up, one line on what it is. Click
   through Customers → Subscriptions so the shape of the app is familiar before
   anything is wrong.
2. **The symptom (0:20–0:45).** Customers page: all three customers wear the
   green **Premium** badge. Then Subscriptions: Cobalt Industries SAS and
   Evergreen Dynamics Ltd ended 2026-03-31 and 2026-09-30. Months ago. Still
   premium. Don't explain the cause — let the contradiction land. *This is the
   moment that makes the rest of the video make sense.*
3. **The "before" (0:45–1:00).** Run `python -m pytest -q`. **9 failed, 75
   passed.** Zoom the failures — every one is an entitlement case. The problem
   exists before the agent is involved.
4. **The ask (1:00–1:10).** Paste the prompt below into Adakode, repo URL and
   all. Type it on camera so the viewer sees you gave it nothing but the repo
   and the symptoms.
5. **The hunt (1:10–1:50).** The agent reads the repo and runs the tests. The
   turn to highlight: the docstring of `has_premium_access` already states the
   correct rule, and the query underneath it doesn't implement it. The code
   contradicts its own contract — a find, not a line you handed over.
6. **The fix (1:50–2:10).** One clause:
   `AND (end_date IS NULL OR end_date >= ?)`. Show the diff — one line, readable,
   applies to everybody, no customer list, no `if customer_id in (...)`.
7. **Green (2:10–2:20).** Rerun. **84 passed.** The nine that were red are the
   nine that turned green.
8. **Proof in the product (2:20–2:45).** Back to the browser — Cobalt and
   Evergreen flip to **No access**, Pulse Analytics GmbH stays **Premium**.
   Seeing the badge flip on screen is the shot the video exists for. (Stale tab?
   Ctrl+F5.)
9. **Close (2:45–3:00).** One line: the agent located the cause from the
   project's own docs and tests, fixed the code, and didn't touch a single test.

Cut beats 1 and 9 first if you need it tighter; never cut beat 2 or beat 8.

### The prompt to give Adakode

```
Fix a bug in my SaaS subscription app: https://github.com/Nazmul92/saas-subscription

Clone the repo, install what it needs, then run the test suite (`python -m pytest -q`).
Nine tests fail. They encode a rule the app is supposed to follow: a customer has
premium access only while they hold an active subscription whose term has not ended
(end_date is null, or today or later). Today a subscription that has already lapsed
still grants access, so expired customers keep the paid features.

Find the root cause and fix it in the application code. Requirements:
- Make the whole suite pass without changing, deleting, or weakening any test.
- The fix applies to every customer — no special-casing individual accounts.
- The Customers page in the web UI must reflect it too (the "Premium access" column).
- Run `python server.py` and check the Customers page in a browser before you finish.

When you're done, show me the diff and the full test output, and tell me in one
sentence what the root cause was.
```

Why each constraint is there: "don't weaken the tests" makes the agent's
restraint visible; "every customer" rules out the shortcut a viewer would
otherwise suspect; the browser check produces beat 8.

After the run, check the agent did all four: suite green, tests untouched, no
per-customer branch in the diff, and the two lapsed customers showing **No
access** in the UI. If any one is missing, that's the interesting part of the
video, not a failed take.

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
