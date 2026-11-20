import json

from browzine_mock.app import create_app
from browzine_mock.store import ROOT
from tests.test_foundation import client, db_path, scalar  # noqa: F401


def test_documented_journey(client, db_path):
    """The 13-step test sequence in docs/DATA_DESIGN.md."""
    r = client.get("/journals?q=neural")
    assert r.status_code == 200 and [j["journal_id"] for j in r.json()["data"]] == ["J03"]
    assert r.json()["data"][0]["in_bookshelf"] is False
    r = client.post("/bookshelf", json={"journal_id": "J03"})
    assert r.status_code == 201 and r.json()["data"]["unread_count"] == 1
    assert client.post("/bookshelf", json={"journal_id": "J03"}).status_code == 409
    r = client.get("/notifications?status=unread").json()
    assert {n["notification_id"] for n in r["data"]} == {"N-I02", "N-I05", "N-I07", "N-I08"}
    assert r["meta"]["unread_count"] == 4
    assert client.post("/notifications/N-I05/read").json()["data"]["read"] is True
    assert client.post("/notifications/N-I05/read").status_code == 409
    r = client.get("/journals/J03/articles?issue_id=I05").json()
    assert [a["article_id"] for a in r["data"]] == ["A013", "A014", "A015"]
    assert client.post("/saved-articles", json={"article_id": "A013"}).status_code == 201
    assert client.post("/saved-articles", json={"article_id": "A013"}).status_code == 409
    assert client.get("/saved-articles/A013/citation?format=bibtex").text.startswith("@article{chan2026a013,")
    assert client.get("/saved-articles/A013/citation?format=ris").text.startswith("TY  - JOUR")
    assert client.get("/saved-articles/A001/citation?format=ris").status_code == 409
    assert client.delete("/bookshelf/J03").status_code == 204
    assert "N-I05" not in [n["notification_id"] for n in client.get("/notifications").json()["data"]]
    assert scalar(db_path, "SELECT read FROM notifications WHERE notification_id='N-I05'") == 1


def operations(spec):
    return {(method.upper(), path): op for path, item in spec["paths"].items() for method, op in item.items()}


def test_live_schema_matches_reviewed_contract(db_path):
    reviewed = operations(json.loads((ROOT / "openapi.json").read_text(encoding="utf-8")))
    live = operations(create_app(db_path).openapi())
    assert set(live) == set(reviewed)
    for key, expected in reviewed.items():
        actual = live[key]
        assert actual["operationId"] == expected["operationId"], key
        assert set(expected["responses"]) == set(actual["responses"]), key
        for code, response in expected["responses"].items():  # e.g. a 409 documented as text/plain
            assert set(response.get("content", {})) == set(actual["responses"][code].get("content", {})), (key, code)
        exp_params = {(p["name"], p["in"], p.get("required", False)) for p in expected.get("parameters", [])}
        act_params = {(p["name"], p["in"], p.get("required", False)) for p in actual.get("parameters", [])}
        assert act_params == exp_params, key


# One real request per documented status of every operation: the Content-Type and body shape it sends
# must be what openapi.json says, so the contract and the service cannot drift apart again.
REAL_RESPONSES = [
    ("get", "/journals?q=neural", None, 200), ("get", "/journals?limit=0", None, 422),
    ("get", "/journals/J03", None, 200), ("get", "/journals/J99", None, 404),
    ("get", "/journals/bad!", None, 422), ("get", "/journals/J03/articles?issue_id=bad!", None, 422),
    ("get", "/saved-articles?x=1", None, 422), ("delete", "/bookshelf/bad!", None, 422),
    ("delete", "/saved-articles/bad!", None, 422),
    ("get", "/journals/J03/articles", None, 200), ("get", "/journals/J99/articles", None, 404),
    ("get", "/bookshelf", None, 200), ("get", "/bookshelf?x=1", None, 422),
    ("post", "/bookshelf", {"journal_id": "J03"}, 201), ("post", "/bookshelf", {"journal_id": "J01"}, 409),
    ("post", "/bookshelf", {"journal_id": "J99"}, 404), ("post", "/bookshelf", {}, 422),
    ("delete", "/bookshelf/J04", None, 204), ("delete", "/bookshelf/J02", None, 409),
    ("delete", "/bookshelf/J99", None, 404),
    ("get", "/notifications", None, 200), ("get", "/notifications?status=x", None, 422),
    ("post", "/notifications/N-I02/read", None, 200), ("post", "/notifications/N-I01/read", None, 409),
    ("post", "/notifications/N-I99/read", None, 404), ("post", "/notifications/N-I07/read", {"read": False}, 422),
    ("post", "/saved-articles", {"article_id": "A013"}, 201), ("get", "/saved-articles", None, 200),
    ("post", "/saved-articles", {"article_id": "A013"}, 409), ("post", "/saved-articles", {"article_id": "A999"}, 404),
    ("post", "/saved-articles", {"article_id": "A013", "x": 1}, 422),
    ("get", "/saved-articles/A013/citation?format=ris", None, 200),
    ("get", "/saved-articles/A001/citation?format=ris", None, 409),
    ("get", "/saved-articles/A999/citation?format=ris", None, 404),
    ("get", "/saved-articles/A013/citation?format=pdf", None, 422),
    ("delete", "/saved-articles/A013", None, 204), ("delete", "/saved-articles/A013", None, 409),
    ("delete", "/saved-articles/A999", None, 404),
    ("get", "/health", None, 200), ("get", "/health?x=1", None, 422),
]


def test_real_responses_match_documented_media_types(client):
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    matched = []
    for method, url, body, code in REAL_RESPONSES:
        r = getattr(client, method)(url, **({} if body is None else {"json": body}))
        assert r.status_code == code, (method, url, r.text)
        path = r.request.url.path
        template = next(p for p in spec["paths"] if p.count("/") == path.count("/") and all(
            a == b or a.startswith("{") for a, b in zip(p.split("/"), path.split("/"))))
        documented = spec["paths"][template][method]["responses"][str(code)].get("content", {})
        actual = r.headers.get("content-type", "").split(";")[0]
        assert ({actual} if r.content else set()) == set(documented), (method, url, code)
        if actual == "application/problem+json":
            assert set(r.json()) >= {"type", "title", "status", "detail", "instance"}
            assert r.json()["status"] == code and (("errors" in r.json()) == (code == 422))
        elif actual == "application/json" and template != "/health":
            assert "data" in r.json() and set(r.json()) <= {"data", "meta"}
        matched.append((template, method, str(code)))
    documented_all = {(p, m, c) for p, item in spec["paths"].items() for m, op in item.items()
                      for c in op["responses"] if c != "503"}
    assert documented_all == set(matched)


def test_problem_keeps_allow_header_and_public_instance(client):
    r = client.put("/bookshelf")
    assert r.status_code == 405 and r.headers.get("allow")  # was dropped by the problem handler
    assert r.headers["content-type"] == "application/problem+json"
    r = client.get("/journals/J99", headers={"X-Forwarded-Prefix": "/student/browzine-mock"})
    assert r.json()["instance"] == "/student/browzine-mock/journals/J99"
    assert client.get("/journals/J99").json()["instance"] == "/journals/J99"


def test_openapi_keeps_app_settings(db_path):
    application = create_app(db_path)
    application.servers = [{"url": "https://example.test"}]
    application.openapi_schema = None
    schema = application.openapi()
    assert schema["servers"] == [{"url": "https://example.test"}] and schema["info"]["version"] == "0.2.0"
    assert application.openapi() is schema  # cached, and adjusting it twice changes nothing
