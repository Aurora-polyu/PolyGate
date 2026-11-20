import json
import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from browzine_mock.app import create_app
from browzine_mock.models import SeedData
from browzine_mock.store import DEFAULT_SEED, ROOT, Store


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.sqlite3"


@pytest.fixture
def client(db_path):
    with TestClient(create_app(db_path)) as test_client:
        yield test_client


def scalar(db_path, sql):
    with sqlite3.connect(db_path) as connection:
        return connection.execute(sql).fetchone()[0]


def test_health_and_docs(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_seed_counts(client, db_path):
    expected = {"journals": 10, "issues": 20, "articles": 60, "notifications": 18,
                "bookshelf": 2, "saved_articles": 0}
    for table, count in expected.items():
        assert scalar(db_path, f"SELECT COUNT(*) FROM {table}") == count, table


def test_relationships(client, db_path):
    with sqlite3.connect(db_path) as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {n for (n,) in c.execute("SELECT COUNT(*) FROM issues GROUP BY journal_id")} == {2}
        assert {n for (n,) in c.execute("SELECT COUNT(*) FROM articles GROUP BY issue_id")} == {3}
        assert c.execute("SELECT issue_id FROM issues WHERE status='in_press' ORDER BY 1").fetchall() == [
            ("I06",), ("I14",)]
        assert c.execute(
            "SELECT COUNT(*) FROM notifications n JOIN issues i USING (issue_id) WHERE i.status='in_press'"
        ).fetchone()[0] == 0
        assert [r[0] for r in c.execute("SELECT journal_id FROM bookshelf ORDER BY position")] == ["J01", "J04"]
        assert c.execute("SELECT issue_id FROM notifications WHERE read=1").fetchall() == [("I01",)]
        assert c.execute(
            "SELECT title, doi, start_page, end_page, authors FROM articles WHERE article_id='A013'"
        ).fetchone() == ("Spiking Network Models for Sensor Fusion", "10.9999/ncl.12.3.101", 101, 115,
                         '["Chan, Wai Ming", "Lee, Sze Yan"]')


def test_restart_preserves_changes(db_path):
    with TestClient(create_app(db_path)):
        pass
    with sqlite3.connect(db_path) as c:
        c.execute("UPDATE notifications SET read=1 WHERE notification_id='N-I02'")
    with TestClient(create_app(db_path)):  # simulated restart or redeploy
        pass
    assert scalar(db_path, "SELECT read FROM notifications WHERE notification_id='N-I02'") == 1
    assert scalar(db_path, "SELECT COUNT(*) FROM journals") == 10


def test_reset_restores_seed(db_path):
    store = Store(db_path)
    store.initialize()
    with sqlite3.connect(db_path) as c:
        c.execute("INSERT INTO saved_articles VALUES ('A001', 1)")
        c.execute("DELETE FROM bookshelf")
    store.reset()
    assert scalar(db_path, "SELECT COUNT(*) FROM saved_articles") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM bookshelf") == 2


def test_refuses_foreign_database(db_path):
    with sqlite3.connect(db_path) as c:
        c.execute("CREATE TABLE other (x)")
    with pytest.raises(RuntimeError):
        Store(db_path).initialize()
    with pytest.raises(RuntimeError):
        Store(db_path).reset()


def test_cli_reset_requires_yes(db_path):
    env = {"POLYGATE_DB_FILE": str(db_path), "PATH": ""}
    refused = subprocess.run([sys.executable, "-m", "browzine_mock", "reset"], cwd=ROOT, env=env,
                             capture_output=True, text=True)
    assert refused.returncode != 0 and not db_path.exists()
    done = subprocess.run([sys.executable, "-m", "browzine_mock", "reset", "--yes"], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert scalar(db_path, "SELECT COUNT(*) FROM articles") == 60


def test_seed_file_is_valid_and_reproducible(tmp_path):
    SeedData.model_validate(json.loads(DEFAULT_SEED.read_text(encoding="utf-8")))
    out = tmp_path / "seed.json"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_seed.py"), "--output", str(out)],
                   check=True, capture_output=True)
    assert out.read_text() == DEFAULT_SEED.read_text()


def test_invalid_seed_is_rejected():
    data = json.loads(DEFAULT_SEED.read_text(encoding="utf-8"))
    data["journals"][0]["issn"] = "1234-5678"  # bad check digit
    with pytest.raises(ValueError):
        SeedData.model_validate(data)
    data = json.loads(DEFAULT_SEED.read_text(encoding="utf-8"))
    data["notifications"].append({"notification_id": "N-I06", "issue_id": "I06", "read": False})
    with pytest.raises(ValueError):
        SeedData.model_validate(data)
