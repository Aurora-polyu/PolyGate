"""Run the user journey against a running service and leave its data exactly as it was.

    python scripts/demo.py [--base-url http://127.0.0.1:8000]
    python scripts/demo.py --base-url https://apps.polylink.org/<username>/<app-name>   # deployed on ceAI+

Safe to run any number of times, on seed data or on data people have changed. The script follows a
journal that is not on the bookshelf and saves an article that is not saved, then undoes both.
Mark-read has no undo, so it is checked only with requests that must be rejected and change nothing.
The run fails unless the bookshelf, notifications and saved articles end identical to how they started.

Run it while nobody else is changing the data: it compares whole-service state, and its cleanup removes
the follow and the save it made, even if someone else made the same follow or save meanwhile.
"""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


# The ceAI+ gateway now and then closes a connection without a response (seen 2026-11-20; the app
# never saw the request). These requests are safe to send again: a GET changes nothing, and a
# repeated DELETE is a 409 that changes nothing. A POST is never resent.
DROPPED = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)
RETRY_ONCE = {"GET", "DELETE"}


def call(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    """Return (status, raw body text); HTTP errors are results, not exceptions."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(base.rstrip("/") + path, data=data, method=method)
    # The ceAI+ gateway rejects Python's default "Python-urllib" User-Agent (403, error 1010).
    request.add_header("User-Agent", "polygate-browzine-demo/1.0")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for attempt in (1, 2):
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8")
        except HTTPError as error:
            return error.code, error.read().decode("utf-8")
        except (URLError, *DROPPED) as error:
            reason = error.reason if isinstance(error, URLError) else error
            if not isinstance(reason, DROPPED):
                raise  # e.g. connection refused: main() reports the service as unreachable
            if method in RETRY_ONCE and attempt == 1:
                print(f"   ({method} {path}: connection dropped, sending it again)", file=sys.stderr)
                continue
            hint = "" if method in RETRY_ONCE else (
                " It may or may not have been applied; check GET /bookshelf and /saved-articles.")
            raise RuntimeError(f"{method} {path}: the connection was dropped without a response.{hint}")
    raise AssertionError("unreachable")


def get_json(base: str, path: str) -> dict:
    status, text = call(base, "GET", path)
    require(status == 200, f"GET {path} returned {status}: {text}")
    return json.loads(text)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def state(base: str) -> dict:
    """Everything the journey can change, so it can be compared before and after."""
    return {"bookshelf": get_json(base, "/bookshelf"), "notifications": get_json(base, "/notifications"),
            "saved": get_json(base, "/saved-articles")}


def pick_targets(base: str) -> tuple[dict, list[dict]]:
    """The first journal that is not on the bookshelf, has a published issue (so following it shows a
    notification) and has an unsaved article; with that journal's unsaved articles."""
    for journal in get_json(base, "/journals?limit=50")["data"]:
        if journal["in_bookshelf"]:
            continue
        issues = get_json(base, f"/journals/{journal['journal_id']}")["data"]["issues"]
        if not any(i["status"] == "published" for i in issues):
            continue
        unsaved = [a for a in get_json(base, f"/journals/{journal['journal_id']}/articles")["data"]
                   if not a["saved"]]
        if unsaved:
            return journal, unsaved
    raise RuntimeError("No journal is both off the bookshelf and has an unsaved article; nothing to try.")


def journey(base: str, undo: list) -> None:
    journal, unsaved = pick_targets(base)
    jid = journal["journal_id"]
    found = get_json(base, "/journals?q=" + quote(journal["title"]))["data"]
    require(jid in [j["journal_id"] for j in found], f"Search by title should find {jid}.")
    print(f"1. Search '{journal['title']}': found {jid}, not on the bookshelf.")

    status, text = call(base, "POST", "/bookshelf", {"journal_id": jid})
    require(status == 201, f"Follow failed: {status} {text}")
    undo.append(("DELETE", f"/bookshelf/{jid}"))
    entry = json.loads(text)["data"]
    notes = get_json(base, "/notifications")
    mine = [n for n in notes["data"] if n["journal_id"] == jid]
    require(mine and entry["unread_count"] == sum(not n["read"] for n in mine),
            f"Following {jid} should show its notifications with a matching unread count.")
    print(f"2. Followed {jid}: 201, {len(mine)} notification(s), {entry['unread_count']} unread.")

    followed = state(base)
    status, _ = call(base, "POST", "/bookshelf", {"journal_id": jid})
    require(status == 409 and state(base) == followed, "A repeated follow must be 409 and change nothing.")
    print(f"3. Follow {jid} again: 409 Conflict; nothing changed.")

    target = next((n for n in mine if not n["read"]), mine[0])
    status, text = call(base, "POST", f"/notifications/{target['notification_id']}/read", {"read": False})
    require(status == 422 and state(base) == followed, f"Mark-read with a body must be 422: {status} {text}")
    read_one = next((n for n in notes["data"] if n["read"]), None)
    if read_one:
        status, _ = call(base, "POST", f"/notifications/{read_one['notification_id']}/read")
        require(status == 409 and state(base) == followed, "Marking a read notification must be 409.")
    print("4. Mark-read with a body: 422" + (f"; {read_one['notification_id']} (already read): 409" if read_one
                                              else "") + ". Nothing changed (mark-read has no undo, so the demo"
          " does not mark anything read).")

    article = unsaved[0]["article_id"]
    print(f"5. {jid} has {len(unsaved)} unsaved article(s); saving {article}.")

    status, text = call(base, "POST", "/saved-articles", {"article_id": article})
    require(status == 201 and json.loads(text)["data"]["saved"] is True, f"Save failed: {status} {text}")
    undo.append(("DELETE", f"/saved-articles/{article}"))
    saved_once = state(base)
    status, _ = call(base, "POST", "/saved-articles", {"article_id": article})
    require(status == 409 and state(base) == saved_once, "A repeated save must be 409 and change nothing.")
    print(f"6. Saved {article}; again: 409.")

    status, bibtex = call(base, "GET", f"/saved-articles/{article}/citation?format=bibtex")
    require(status == 200 and bibtex.startswith("@article{"), f"BibTeX export failed: {status}")
    status, ris = call(base, "GET", f"/saved-articles/{article}/citation?format=ris")
    require(status == 200 and ris.startswith("TY  - JOUR") and ris.endswith("ER  - \n"), "RIS export failed.")
    print(f"7. Exported {article} as BibTeX and RIS:\n" + bibtex.rstrip() + "\n")

    other = next((a["article_id"] for a in unsaved[1:]), None)
    if other:
        status, text = call(base, "GET", f"/saved-articles/{other}/citation?format=ris")
        require(status == 409 and json.loads(text)["status"] == 409 and state(base) == saved_once,
                "Exporting an unsaved article must be 409 problem+json and change nothing.")
        print(f"8. Export unsaved {other}: 409 Conflict; nothing changed.")


def demo(base: str) -> None:
    require(get_json(base, "/health") == {"status": "ok"}, "Health check failed.")
    start = state(base)
    undo: list[tuple[str, str]] = []
    try:
        journey(base, undo)
    finally:  # undo what this run created, newest first, even if a check failed
        for method, path in reversed(undo):
            try:
                status, text = call(base, method, path)
            except RuntimeError as error:
                status, text = None, str(error)
            if status not in (204, 409):  # 409: an earlier, dropped attempt already removed it
                print(f"Cleanup {method} {path} failed ({status}): {text}", file=sys.stderr)
    require(state(base) == start, "The data is not the same as before the run.")
    print("9. Undid the follow and the save. Bookshelf, notifications and saved articles match the start.")
    print("Journey complete; data unchanged. Safe to run again.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        demo(args.base_url)
    except URLError as error:
        print(f"Cannot reach {args.base_url}: {error.reason}. Is the service running?", file=sys.stderr)
        return 2
    except RuntimeError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
