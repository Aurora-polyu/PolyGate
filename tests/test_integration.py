"""Phase 5: data consistency across features, rejected requests changing nothing, citation validation."""

import json
import re
import sqlite3

import pytest

from browzine_mock.store import DEFAULT_SEED
from tests.test_foundation import client, db_path, scalar  # noqa: F401

TABLES = ("journals", "issues", "articles", "bookshelf", "saved_articles", "notifications")


def snapshot(db_path):
    """Every row of every table, so any stray write shows up."""
    with sqlite3.connect(db_path) as connection:
        return {t: connection.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in TABLES}


# One request per rejection class for every operation that can change data (or could be mistaken for one).
REJECTED = [
    ("post", "/bookshelf", {"journal_id": "J01"}, 409),
    ("post", "/bookshelf", {"journal_id": "J99"}, 404),
    ("post", "/bookshelf", {"journal_id": "J03", "x": 1}, 422),
    ("delete", "/bookshelf/J02", None, 409),
    ("delete", "/bookshelf/J99", None, 404),
    ("post", "/notifications/N-I01/read", None, 409),
    ("post", "/notifications/N-I03/read", None, 404),
    ("post", "/notifications/bad id!/read", None, 422),
    ("post", "/notifications/N-I02/read", {"read": False}, 422),
    ("post", "/saved-articles", {"article_id": "A999"}, 404),
    ("post", "/saved-articles", {"article_id": "A001", "x": 1}, 422),
    ("delete", "/saved-articles/A001", None, 409),
    ("delete", "/saved-articles/A999", None, 404),
    ("get", "/saved-articles/A001/citation?format=ris", None, 409),
    ("get", "/saved-articles/A999/citation?format=ris", None, 404),
    ("get", "/saved-articles/A001/citation?format=pdf", None, 422),
    ("get", "/journals?limit=1&limit=2", None, 422),
]


@pytest.mark.parametrize("method,url,body,code", REJECTED)
def test_rejected_request_changes_nothing(client, db_path, method, url, body, code):
    before = snapshot(db_path)
    kwargs = {} if body is None else {"json": body}
    assert getattr(client, method)(url, **kwargs).status_code == code
    assert snapshot(db_path) == before


def test_repeated_success_changes_data_once(client, db_path):
    """Doing the same action twice: the first changes the data, the repeat is a 409 and changes nothing."""
    for first, again, repeat in [
        (("post", "/bookshelf", {"journal_id": "J03"}), ("post", "/bookshelf", {"journal_id": "J03"}), 409),
        (("post", "/saved-articles", {"article_id": "A013"}),
         ("post", "/saved-articles", {"article_id": "A013"}), 409),
        (("post", "/notifications/N-I02/read", None), ("post", "/notifications/N-I02/read", None), 409),
        (("delete", "/saved-articles/A013", None), ("delete", "/saved-articles/A013", None), 409),
        (("delete", "/bookshelf/J03", None), ("delete", "/bookshelf/J03", None), 409),
    ]:
        def send(call):
            method, url, body = call
            return getattr(client, method)(url, **({} if body is None else {"json": body}))
        assert send(first).status_code in (200, 201, 204)
        after_first = snapshot(db_path)
        assert send(again).status_code == repeat
        assert snapshot(db_path) == after_first


def test_features_stay_consistent(client, db_path):
    """Bookshelf unread counts, notifications, saved articles and search flags always agree."""
    client.post("/bookshelf", json={"journal_id": "J03"})
    client.post("/saved-articles", json={"article_id": "A013"})
    client.post("/notifications/N-I05/read")

    notes = client.get("/notifications").json()
    shelf = client.get("/bookshelf").json()["data"]
    assert {e["journal_id"] for e in shelf} == {"J01", "J03", "J04"}
    for entry in shelf:  # per-journal unread_count == unread notifications for that journal
        mine = [n for n in notes["data"] if n["journal_id"] == entry["journal_id"] and not n["read"]]
        assert entry["unread_count"] == len(mine)
    assert notes["meta"]["unread_count"] == sum(e["unread_count"] for e in shelf)
    assert {n["journal_id"] for n in notes["data"]} <= {e["journal_id"] for e in shelf}

    found = client.get("/journals?q=neural").json()["data"]
    assert [j["in_bookshelf"] for j in found] == [True]
    saved = client.get("/saved-articles").json()["data"]
    listed = client.get("/journals/J03/articles?issue_id=I05").json()["data"]
    assert {a["article_id"] for a in listed if a["saved"]} == {a["article_id"] for a in saved} == {"A013"}

    client.delete("/bookshelf/J03")  # saved articles do not depend on the bookshelf
    assert [a["article_id"] for a in client.get("/saved-articles").json()["data"]] == ["A013"]
    assert client.get("/saved-articles/A013/citation?format=ris").status_code == 200
    assert client.get("/journals?q=neural").json()["data"][0]["in_bookshelf"] is False


def test_database_relationships_hold_after_a_journey(client, db_path):
    client.post("/bookshelf", json={"journal_id": "J03"})
    client.post("/saved-articles", json={"article_id": "A013"})
    client.delete("/bookshelf/J03")
    with sqlite3.connect(db_path) as c:
        assert c.execute("PRAGMA foreign_key_check").fetchall() == []
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert scalar(db_path, "SELECT COUNT(*) FROM articles") == 60
    assert scalar(db_path, "SELECT COUNT(*) FROM journals") == 10


# --- citation validation over every seeded article ---------------------------------------------

ALL_ARTICLES = [a["article_id"] for a in json.loads(DEFAULT_SEED.read_text(encoding="utf-8"))["articles"]]


def parse_bibtex(text):
    head = re.fullmatch(r"@article\{([a-z0-9]+),\n(.*)\n\}\n", text, re.DOTALL)
    assert head, text
    fields = dict(re.fullmatch(r"  (\w+) = \{(.*)\}", line).groups() for line in head.group(2).split(",\n"))
    return head.group(1), fields


def parse_ris(text):
    assert text.endswith("ER  - \n")
    return [re.fullmatch(r"([A-Z][A-Z0-9])  - (.*)", line).groups() for line in text.splitlines()]


def test_every_seeded_article_exports_valid_bibtex_and_ris(client):
    assert len(ALL_ARTICLES) == 60
    for article_id in ALL_ARTICLES:
        assert client.post("/saved-articles", json={"article_id": article_id}).status_code == 201
    stored = {a["article_id"]: a for a in client.get("/saved-articles").json()["data"]}
    keys = set()
    for article_id, a in stored.items():
        bib = client.get(f"/saved-articles/{article_id}/citation?format=bibtex").text
        key, f = parse_bibtex(bib)
        assert key not in keys
        keys.add(key)
        assert key == re.sub("[^a-z0-9]", "", a["authors"][0].split(",")[0].lower()) + f"{a['year']}{article_id.lower()}"
        assert set(f) == {"author", "title", "journal", "year", "volume", "number", "pages", "doi", "issn"}
        assert f["author"] == " and ".join(a["authors"]) and f["title"] == a["title"]
        assert f["pages"] == f"{a['start_page']}--{a['end_page']}" and f["doi"] == a["doi"]
        assert re.fullmatch(r"\d{4}-\d{3}[\dX]", f["issn"]) and re.fullmatch(r"10\.\d{4,}/\S+", f["doi"])
        assert not re.search(r"[{}\\%&#_$~^]", f["title"] + f["author"] + f["journal"])  # nothing needing escapes
        assert bib.count("{") == bib.count("}")

        pairs = parse_ris(client.get(f"/saved-articles/{article_id}/citation?format=ris").text)
        tags = [t for t, _ in pairs]
        assert tags[0] == "TY" and tags[-1] == "ER" and pairs[0][1] == "JOUR"
        assert [v for t, v in pairs if t == "AU"] == a["authors"]
        assert dict(pairs)["TI"] == a["title"] and dict(pairs)["SP"] == str(a["start_page"])
        assert {"TI", "JO", "PY", "VL", "IS", "SP", "EP", "DO", "SN"} <= set(tags)
    assert len(keys) == 60  # BibTeX keys are unique across the data set
