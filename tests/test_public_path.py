import pytest

from tests.test_foundation import client, db_path  # noqa: F401

PREFIX = "/student/browzine-mock"


def hdr(value):
    return {"X-Forwarded-Prefix": value}


def test_prefix_reaches_docs_and_schema(client):
    docs = client.get("/docs", headers=hdr(PREFIX)).text
    assert f"{PREFIX}/openapi.json" in docs
    assert client.get("/openapi.json", headers=hdr(PREFIX)).json()["servers"] == [{"url": PREFIX}]


def test_routes_unchanged_with_prefix(client):
    assert client.get("/health", headers=hdr(PREFIX)).json() == {"status": "ok"}
    assert client.get("/journals?q=neural", headers=hdr(PREFIX)).status_code == 200
    assert client.get(f"{PREFIX}/health").status_code == 404  # the gateway strips it; the app never sees it


def test_without_header_behaviour_is_unchanged(client):
    docs = client.get("/docs").text
    assert "'/openapi.json'" in docs or '"/openapi.json"' in docs
    assert "servers" not in client.get("/openapi.json").json()


@pytest.mark.parametrize("value", [
    "//evil", "/a/../b", "http://x.test/a", "/a b", "/student/browzine-mock/", "/" + "a" * 200, "", "/",
    "/a/b/c", "/journals", "/health", "/a?x=1", "/a\\b", "/.."])
def test_bad_prefix_is_ignored(client, value):
    assert "servers" not in client.get("/openapi.json", headers=hdr(value)).json()
    assert client.get("/health", headers=hdr(value)).status_code == 200
