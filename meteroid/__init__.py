"""Meteroid - a small, self-contained SaaS subscription billing app.

The package is split into three layers:

* :mod:`meteroid.db`      - SQLite schema and connection handling.
* :mod:`meteroid.billing` - the billing rules (subscriptions, MRR, invoices).
* :mod:`meteroid.api`     - a WSGI HTTP API plus the static frontend.

Everything uses the Python standard library only.
"""

__version__ = "1.0.0"
