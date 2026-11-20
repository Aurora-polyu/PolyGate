import pytest

from tests.test_foundation import client, db_path  # noqa: F401  (shared fixtures)


def test_search_by_title(client):
    body = client.get("/journals", params={"q": "NEURAL"}).json()
    assert body == {"data": [{"journal_id": "J03", "title": "Neural Computation Letters",
                               "issn": "2049-3630", "subject": "Artificial Intelligence",
                               "in_bookshelf": False}], "meta": {"total": 1, "limit": 20, "offset": 0}}


def test_search_all_sorted_and_paged(client):
    everything = client.get("/journals", params={"limit": 50}).json()
    titles = [j["title"] for j in everything["data"]]
    assert everything["meta"]["total"] == 10 and titles == sorted(titles, key=str.lower)
    page = client.get("/journals", params={"limit": 3, "offset": 9}).json()
    assert page["meta"]["total"] == 10 and [j["title"] for j in page["data"]] == titles[9:]


def test_search_filters_combine_and_flag_bookshelf(client):
    body = client.get("/journals", params={"subject": "computer vision"}).json()
    assert body["meta"]["total"] == 2 and {j["journal_id"] for j in body["data"]} == {"J04", "J05"}
    assert {j["journal_id"]: j["in_bookshelf"] for j in body["data"]} == {"J04": True, "J05": False}
    assert client.get("/journals", params={"subject": "Computer Vision", "q": "zzz"}).json()["meta"]["total"] == 0
    assert client.get("/journals", params={"issn": "2049-3630"}).json()["data"][0]["journal_id"] == "J03"


def test_search_no_match_is_empty_200(client):
    r = client.get("/journals", params={"q": "zzz"})
    assert r.status_code == 200 and r.json()["data"] == [] and r.json()["meta"]["total"] == 0


@pytest.mark.parametrize("params", [
    {"issn": "1234"}, {"limit": 0}, {"limit": 51}, {"offset": -1}, {"q": ""}, {"bogus": "1"}])
def test_search_rejects_invalid_input(client, params):
    r = client.get("/journals", params=params)
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"
    assert r.json()["status"] == 422 and len(r.json()["errors"]) == 1 and "parameter" in r.json()["errors"][0]


def test_unknown_query_param_rejected_on_every_route(client):
    for url in ("/health", "/journals/J03", "/journals?q=a&x=1"):
        sep = "&" if "?" in url else "?"
        assert client.get(f"{url}{sep}x=1").status_code == 422, url
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("url", [
    "/journals?limit=1&limit=2", "/journals?q=a&q=b", "/notifications?status=read&status=all",
    "/journals/J03/articles?issue_id=I05&issue_id=I06", "/bookshelf?x=1&x=2"])
def test_repeated_query_param_rejected(client, url):
    assert client.get(url).status_code == 422


def test_journal_details(client):
    body = client.get("/journals/J03").json()["data"]
    assert body["title"] == "Neural Computation Letters" and body["publisher"] == "PolyGate Synthetic Press"
    assert body["in_bookshelf"] is False
    assert body["issues"] == [
        {"issue_id": "I06", "volume": 12, "issue_number": 4, "year": 2026, "publication_date": None,
         "status": "in_press", "article_count": 3},
        {"issue_id": "I05", "volume": 12, "issue_number": 3, "year": 2026, "publication_date": "2026-09-15",
         "status": "published", "article_count": 3}]
    assert client.get("/journals/J01").json()["data"]["in_bookshelf"] is True


def test_journal_details_rejections(client):
    r = client.get("/journals/J99")
    assert r.status_code == 404 and r.json() == {
        "type": "about:blank", "title": "Not Found", "status": 404, "detail": "Journal J99 does not exist.",
        "instance": "/journals/J99"}
    assert client.get("/journals/bad id!").status_code == 422
    assert client.get("/journals/-J01").status_code == 422
