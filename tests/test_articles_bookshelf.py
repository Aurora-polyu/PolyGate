import sqlite3

import pytest

from tests.test_foundation import client, db_path, scalar  # noqa: F401


def test_articles_by_issue(client):
    body = client.get("/journals/J03/articles", params={"issue_id": "I05"}).json()
    assert [a["article_id"] for a in body["data"]] == ["A013", "A014", "A015"]
    a = body["data"][0]
    assert a == {"article_id": "A013", "journal_id": "J03", "journal_title": "Neural Computation Letters",
                 "issue_id": "I05", "volume": 12, "issue_number": 3, "year": 2026,
                 "title": "Spiking Network Models for Sensor Fusion",
                 "authors": ["Chan, Wai Ming", "Lee, Sze Yan"], "start_page": 101, "end_page": 115,
                 "doi": "10.9999/ncl.12.3.101", "saved": False}


def test_articles_whole_journal_newest_first_includes_in_press(client):
    ids = [a["article_id"] for a in client.get("/journals/J03/articles").json()["data"]]
    assert ids == ["A016", "A017", "A018", "A013", "A014", "A015"]  # I06 (in press) first


@pytest.mark.parametrize("url,code", [
    ("/journals/J99/articles", 404), ("/journals/J03/articles?issue_id=I99", 404),
    ("/journals/J03/articles?issue_id=I01", 404),  # I01 belongs to J01
    ("/journals/bad id!/articles", 422), ("/journals/J03/articles?issue_id=bad!", 422),
    ("/journals/J03/articles?x=1", 422)])
def test_articles_rejections(client, url, code):
    assert client.get(url).status_code == code


def test_bookshelf_seed_and_unread_counts(client):
    body = client.get("/bookshelf").json()
    assert [(e["journal_id"], e["unread_count"]) for e in body["data"]] == [("J01", 1), ("J04", 2)]
    assert set(body["data"][0]) == {"journal_id", "title", "issn", "subject", "unread_count"}


def test_follow_unfollow_flow(client, db_path):
    r = client.post("/bookshelf", json={"journal_id": "J03"})
    assert r.status_code == 201 and r.json()["data"]["unread_count"] == 1
    assert [e["journal_id"] for e in client.get("/bookshelf").json()["data"]] == ["J01", "J04", "J03"]
    assert client.get("/journals/J03").json()["data"]["in_bookshelf"] is True
    assert client.post("/bookshelf", json={"journal_id": "J03"}).status_code == 409
    assert scalar(db_path, "SELECT COUNT(*) FROM bookshelf") == 3
    r = client.delete("/bookshelf/J03")
    assert r.status_code == 204 and r.content == b""
    assert client.delete("/bookshelf/J03").status_code == 409
    assert scalar(db_path, "SELECT COUNT(*) FROM bookshelf") == 2
    assert client.post("/bookshelf", json={"journal_id": "J03"}).status_code == 201  # follow again


def test_unfollow_keeps_notification_state(client, db_path):
    with sqlite3.connect(db_path) as c:
        c.execute("UPDATE notifications SET read=1 WHERE notification_id='N-I07'")
    client.delete("/bookshelf/J04")
    assert client.post("/bookshelf", json={"journal_id": "J04"}).json()["data"]["unread_count"] == 1  # I08 only


@pytest.mark.parametrize("body", [{}, {"journal_id": "bad id"}, {"journal_id": "J03", "x": 1},
                                  {"journal_id": 3}])
def test_follow_invalid_body(client, body):
    assert client.post("/bookshelf", json=body).status_code == 422


def test_bookshelf_rejections(client, db_path):
    assert client.post("/bookshelf", json={"journal_id": "J99"}).status_code == 404
    assert client.post("/bookshelf").status_code == 422
    assert client.delete("/bookshelf/J99").status_code == 404
    assert client.delete("/bookshelf/bad id!").status_code == 422
    assert client.delete("/bookshelf/J02").status_code == 409  # known but not followed
    assert client.get("/bookshelf?x=1").status_code == 422
    assert scalar(db_path, "SELECT COUNT(*) FROM bookshelf") == 2


def test_read_sees_one_moment(client, db_path):
    """A read holds its snapshot: a write cannot commit between two SELECTs of the same request."""
    store = client.app.state.store
    count = "SELECT COUNT(*) FROM notifications WHERE read = 0"
    with store.connection() as c:
        before = c.execute(count).fetchone()[0]
        writer = sqlite3.connect(db_path, timeout=0.1, isolation_level=None)
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE notifications SET read = 1 WHERE notification_id = 'N-I02'")
            writer.execute("COMMIT")
        writer.close()
        assert c.execute(count).fetchone()[0] == before


def test_list_bookshelf_is_one_statement(client, monkeypatch):
    statements = []
    real_connect = sqlite3.connect

    def traced(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr("browzine_mock.store.sqlite3.connect", traced)
    client.get("/bookshelf")
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1 and "FROM bookshelf b JOIN journals" in selects[0]
