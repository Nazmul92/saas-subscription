"""Run the Meteroid app.

    python server.py                 # http://127.0.0.1:8000
    python server.py --port 9000
    python server.py --reset         # delete the database and re-seed

Environment variables: ``METEROID_DB`` (database file), ``PORT``.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server

from meteroid.api import create_app
from meteroid.db import db_path, open_db
from meteroid.seed import seed_demo


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def bootstrap(path: str, reset: bool = False, seed: bool = True):
    """Prepare the database and return the WSGI application."""
    if reset:
        Path(path).unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)
    conn = open_db(path)
    if seed:
        seed_demo(conn)
    conn.close()
    return create_app(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Meteroid subscription billing")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--db", default=db_path())
    parser.add_argument("--reset", action="store_true", help="delete and re-seed the database")
    parser.add_argument("--no-seed", action="store_true", help="do not insert demo data")
    args = parser.parse_args()

    app = bootstrap(args.db, reset=args.reset, seed=not args.no_seed)
    with make_server(args.host, args.port, app, server_class=ThreadingWSGIServer) as httpd:
        print(f"Meteroid running on http://{args.host}:{args.port}  (db: {args.db})")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
