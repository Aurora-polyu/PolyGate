"""scripts/demo.py run against a real server process (not TestClient), as a user would run it."""

import os
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

import json
import sqlite3
from urllib.request import Request

import pytest

from browzine_mock.store import ROOT


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path):
    port = free_port()
    db_path = tmp_path / "live.sqlite3"
    env = {**os.environ, "POLYGATE_DB_FILE": str(db_path)}
    proc = subprocess.Popen([sys.executable, "-m", "browzine_mock", "serve", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urlopen(base + "/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("server did not start")
        yield base, db_path
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def run_demo(base):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "demo.py"), "--base-url", base],
                          capture_output=True, text=True, timeout=60)


def table_dump(db_path):
    with sqlite3.connect(db_path) as connection:
        return {t: connection.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                for t in ("bookshelf", "saved_articles", "notifications")}


def post(base, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(base + path, data=data, method="POST", headers={"Content-Type": "application/json"})
    urlopen(request, timeout=5).close()


def test_demo_repeats_and_keeps_existing_data(live_server):
    base, db_path = live_server
    for _ in range(2):  # seed data
        before = table_dump(db_path)
        result = run_demo(base)
        assert result.returncode == 0, result.stderr
        assert "data unchanged" in result.stdout and table_dump(db_path) == before
    post(base, "/saved-articles", {"article_id": "A013"})  # data people have changed
    post(base, "/bookshelf", {"journal_id": "J03"})
    post(base, "/notifications/N-I05/read")
    for article in ("A055", "A056", "A057", "A058", "A059", "A060"):  # every article of J10, picked first
        post(base, "/saved-articles", {"article_id": article})
    for _ in range(2):
        before = table_dump(db_path)
        result = run_demo(base)
        assert result.returncode == 0, result.stderr
        assert table_dump(db_path) == before


def test_demo_reports_unreachable_service():
    result = run_demo(f"http://127.0.0.1:{free_port()}")
    assert result.returncode == 2 and "Cannot reach" in result.stderr


def load_demo():
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo", ROOT / "scripts" / "demo.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return b'{"status": "ok"}'


def flaky_urlopen(calls, fail_times, error):
    def fake(request, timeout):
        calls.append(request.get_method())
        if len(calls) <= fail_times:
            raise error
        return FakeResponse()
    return fake


def test_demo_retries_a_dropped_get_once(monkeypatch):
    from http.client import RemoteDisconnected
    demo, calls = load_demo(), []
    monkeypatch.setattr(demo, "urlopen", flaky_urlopen(calls, 1, RemoteDisconnected("closed")))
    assert demo.call("http://x", "GET", "/health") == (200, '{"status": "ok"}') and calls == ["GET", "GET"]
    calls.clear()
    monkeypatch.setattr(demo, "urlopen", flaky_urlopen(calls, 2, RemoteDisconnected("closed")))
    with pytest.raises(RuntimeError, match="dropped"):
        demo.call("http://x", "GET", "/health")


def test_demo_never_resends_a_dropped_post(monkeypatch):
    from http.client import RemoteDisconnected
    demo, calls = load_demo(), []
    monkeypatch.setattr(demo, "urlopen", flaky_urlopen(calls, 1, RemoteDisconnected("closed")))
    with pytest.raises(RuntimeError, match="may or may not have been applied"):
        demo.call("http://x", "POST", "/saved-articles", {"article_id": "A013"})
    assert calls == ["POST"]


def test_demo_does_not_retry_a_refused_connection(monkeypatch):
    from urllib.error import URLError
    demo, calls = load_demo(), []
    monkeypatch.setattr(demo, "urlopen", flaky_urlopen(calls, 5, URLError(ConnectionRefusedError())))
    with pytest.raises(URLError):
        demo.call("http://x", "GET", "/health")
    assert calls == ["GET"]
