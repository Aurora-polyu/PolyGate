import pytest

from tests.test_foundation import client, db_path, scalar  # noqa: F401


def ids(body):
    return [n["notification_id"] for n in body["data"]]


def test_fresh_notifications(client):
    body = client.get("/notifications").json()
    assert ids(body) == ["N-I08", "N-I02", "N-I07", "N-I01"]  # publication date, newest first
    assert body["meta"]["unread_count"] == 3
    dates = [n["publication_date"] for n in body["data"]]
    assert dates == sorted(dates, reverse=True)
    unread = client.get("/notifications", params={"status": "unread"}).json()
    assert set(ids(unread)) == {"N-I02", "N-I07", "N-I08"} and unread["meta"]["unread_count"] == 3
    read = client.get("/notifications", params={"status": "read"}).json()
    assert ids(read) == ["N-I01"] and read["meta"]["unread_count"] == 3  # count ignores the filter
    assert set(body["data"][0]) == {"notification_id", "journal_id", "journal_title", "issue_id",
                                             "volume", "issue_number", "publication_date", "article_count",
                                             "read"}


def test_follow_adds_notification_but_not_for_in_press(client):
    client.post("/bookshelf", json={"journal_id": "J03"})
    body = client.get("/notifications", params={"status": "unread"}).json()
    assert set(ids(body)) == {"N-I02", "N-I05", "N-I07", "N-I08"} and body["meta"]["unread_count"] == 4
    assert "N-I06" not in ids(client.get("/notifications").json())
    assert client.post("/notifications/N-I06/read").status_code == 404  # in-press issue: none exists


def test_mark_read_then_repeat(client, db_path):
    r = client.post("/notifications/N-I02/read")
    assert r.status_code == 200 and r.json()["data"]["read"] is True
    assert scalar(db_path, "SELECT read FROM notifications WHERE notification_id='N-I02'") == 1
    assert client.post("/notifications/N-I02/read").status_code == 409
    assert client.get("/notifications").json()["meta"]["unread_count"] == 2


@pytest.mark.parametrize("kwargs", [{"json": {"read": False}}, {"json": {}}, {"content": b"x"}])
def test_mark_read_rejects_any_body(client, db_path, kwargs):
    r = client.post("/notifications/N-I02/read", **kwargs)
    assert r.status_code == 422
    assert scalar(db_path, "SELECT read FROM notifications WHERE notification_id='N-I02'") == 0


def test_unfollow_hides_and_keeps_read_state(client, db_path):
    client.post("/bookshelf", json={"journal_id": "J03"})
    client.post("/notifications/N-I05/read")
    client.delete("/bookshelf/J03")
    assert "N-I05" not in ids(client.get("/notifications").json())
    assert client.post("/notifications/N-I05/read").status_code == 404
    assert scalar(db_path, "SELECT read FROM notifications WHERE notification_id='N-I05'") == 1
    client.post("/bookshelf", json={"journal_id": "J03"})
    assert next(n for n in client.get("/notifications").json()["data"]
                if n["notification_id"] == "N-I05")["read"] is True


@pytest.mark.parametrize("method,url,code", [
    ("get", "/notifications?status=bogus", 422), ("get", "/notifications?x=1", 422),
    ("post", "/notifications/N-I03/read", 404),  # J02 not followed
    ("post", "/notifications/N-I99/read", 404), ("post", "/notifications/bad id!/read", 422)])
def test_notification_rejections(client, method, url, code):
    assert getattr(client, method)(url).status_code == code


def test_save_list_remove(client, db_path):
    assert client.get("/saved-articles").json() == {"data": []}
    r = client.post("/saved-articles", json={"article_id": "A013"})
    assert r.status_code == 201 and r.json()["data"]["saved"] is True and r.json()["data"]["title"].startswith("Spiking")
    assert client.post("/saved-articles", json={"article_id": "A013"}).status_code == 409
    client.post("/saved-articles", json={"article_id": "A001"})  # journal J01 is followed; J03 is not
    assert [a["article_id"] for a in client.get("/saved-articles").json()["data"]] == ["A013", "A001"]
    assert scalar(db_path, "SELECT COUNT(*) FROM saved_articles") == 2
    assert client.get("/journals/J03/articles?issue_id=I05").json()["data"][0]["saved"] is True
    assert client.delete("/saved-articles/A013").status_code == 204
    assert client.delete("/saved-articles/A013").status_code == 409
    assert scalar(db_path, "SELECT COUNT(*) FROM saved_articles") == 1


@pytest.mark.parametrize("method,url,body,code", [
    ("post", "/saved-articles", {"article_id": "A999"}, 404),
    ("post", "/saved-articles", {}, 422), ("post", "/saved-articles", {"article_id": "bad id"}, 422),
    ("post", "/saved-articles", {"article_id": "A001", "x": 1}, 422),
    ("delete", "/saved-articles/A999", None, 404), ("delete", "/saved-articles/bad id!", None, 422),
    ("delete", "/saved-articles/A001", None, 409),  # known but not saved
    ("get", "/saved-articles?x=1", None, 422)])
def test_saved_rejections(client, db_path, method, url, body, code):
    kwargs = {} if body is None else {"json": body}
    assert getattr(client, method)(url, **kwargs).status_code == code
    assert scalar(db_path, "SELECT COUNT(*) FROM saved_articles") == 0
