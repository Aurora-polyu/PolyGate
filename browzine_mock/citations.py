"""BibTeX and RIS records built only from stored article metadata (format defined in docs/API_DESIGN.md)."""

import re


def bibtex_key(article: dict) -> str:
    surname = article["authors"][0].split(",")[0]
    return f"{re.sub('[^a-z0-9]', '', surname.lower())}{article['year']}{article['article_id'].lower()}"


def to_bibtex(a: dict) -> str:
    fields = [
        ("author", " and ".join(a["authors"])), ("title", a["title"]), ("journal", a["journal_title"]),
        ("year", a["year"]), ("volume", a["volume"]), ("number", a["issue_number"]),
        ("pages", f"{a['start_page']}--{a['end_page']}"), ("doi", a["doi"]), ("issn", a["issn"]),
    ]
    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@article{{{bibtex_key(a)},\n{body}\n}}\n"


def to_ris(a: dict) -> str:
    lines = [("TY", "JOUR"), *[("AU", name) for name in a["authors"]], ("TI", a["title"]),
             ("JO", a["journal_title"]), ("PY", a["year"]), ("VL", a["volume"]), ("IS", a["issue_number"]),
             ("SP", a["start_page"]), ("EP", a["end_page"]), ("DO", a["doi"]), ("SN", a["issn"]),
             ("ER", "")]
    return "".join(f"{tag}  - {value}\n" for tag, value in lines)
