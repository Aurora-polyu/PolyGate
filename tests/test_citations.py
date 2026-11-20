import pytest

from tests.test_foundation import client, db_path  # noqa: F401

BIBTEX = """@article{chan2026a013,
  author = {Chan, Wai Ming and Lee, Sze Yan},
  title = {Spiking Network Models for Sensor Fusion},
  journal = {Neural Computation Letters},
  year = {2026},
  volume = {12},
  number = {3},
  pages = {101--115},
  doi = {10.9999/ncl.12.3.101},
  issn = {2049-3630}
}
"""
RIS = ("TY  - JOUR\nAU  - Chan, Wai Ming\nAU  - Lee, Sze Yan\nTI  - Spiking Network Models for Sensor Fusion\n"
       "JO  - Neural Computation Letters\nPY  - 2026\nVL  - 12\nIS  - 3\nSP  - 101\nEP  - 115\n"
       "DO  - 10.9999/ncl.12.3.101\nSN  - 2049-3630\nER  - \n")


def test_bibtex_and_ris_match_design(client):
    client.post("/saved-articles", json={"article_id": "A013"})
    r = client.get("/saved-articles/A013/citation", params={"format": "bibtex"})
    assert r.status_code == 200 and r.headers["content-type"] == "text/plain; charset=utf-8"
    assert r.text == BIBTEX
    r = client.get("/saved-articles/A013/citation", params={"format": "ris"})
    assert r.status_code == 200 and r.text == RIS


def test_citation_reflects_every_author_and_stored_data(client):
    client.post("/saved-articles", json={"article_id": "A001"})
    stored = next(a for a in client.get("/saved-articles").json()["data"])
    ris = client.get("/saved-articles/A001/citation?format=ris").text
    assert ris.count("AU  - ") == len(stored["authors"]) and f"TI  - {stored['title']}\n" in ris
    bib = client.get("/saved-articles/A001/citation?format=bibtex").text
    assert f"doi = {{{stored['doi']}}}" in bib and bib.startswith("@article{")


@pytest.mark.parametrize("url,code", [
    ("/saved-articles/A001/citation?format=ris", 409),  # exists, not saved
    ("/saved-articles/A999/citation?format=ris", 404),
    ("/saved-articles/A013/citation?format=pdf", 422), ("/saved-articles/A013/citation", 422),
    ("/saved-articles/bad id!/citation?format=ris", 422),
    ("/saved-articles/A013/citation?format=ris&x=1", 422)])
def test_citation_rejections(client, url, code):
    assert client.get(url).status_code == code
