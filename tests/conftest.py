"""Shared fixtures: a throwaway database and a live HTTP client."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from wsgiref.simple_server import make_server

from meteroid.db import open_db
from meteroid.seed import seed_demo
from server import ThreadingWSGIServer, bootstrap


class Client:
    """Minimal JSON HTTP client for the running test server."""

    def __init__(self, base: str):
        self.base = base

    def request(self, method: str, path: str, payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                body = res.read().decode("utf-8")
                return res.status, (json.loads(body) if body else None)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            return exc.code, (json.loads(body) if body else None)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, payload=None):
        return self.request("POST", path, payload if payload is not None else {})


@pytest.fixture
def db_file(tmp_path):
    return str(tmp_path / "meteroid-test.db")


@pytest.fixture
def conn(db_file):
    connection = open_db(db_file)
    yield connection
    connection.close()


@pytest.fixture
def seeded(conn):
    """A connection with customers, versioned plans and subscriptions."""
    assert seed_demo(conn) is True
    return conn


@pytest.fixture
def client(db_file):
    """A real HTTP server on a random port, backed by an empty database."""
    app = bootstrap(db_file, reset=True, seed=False)
    httpd = make_server("127.0.0.1", 0, app, server_class=ThreadingWSGIServer)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(f"http://127.0.0.1:{httpd.server_address[1]}")
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()
