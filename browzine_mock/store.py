"""SQLite storage: schema, seeding and reset. query methods."""

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Iterator

from .models import SeedData

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = ROOT / "data" / "mock_data.json"
DEFAULT_DB = ROOT / "data" / "browzine.sqlite3"
APPLICATION_ID = 0x50474231  # "PGB1": only reset databases created by this service.
TABLES = {"journals", "issues", "articles", "bookshelf", "saved_articles", "notifications"}

SCHEMA = """
CREATE TABLE journals (
    journal_id TEXT PRIMARY KEY, title TEXT NOT NULL, issn TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL, publisher TEXT NOT NULL
);
CREATE TABLE issues (
    issue_id TEXT PRIMARY KEY,
    journal_id TEXT NOT NULL REFERENCES journals(journal_id),
    volume INTEGER NOT NULL, issue_number INTEGER NOT NULL, year INTEGER NOT NULL,
    publication_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('published', 'in_press')),
    CHECK ((status = 'in_press') = (publication_date IS NULL))
);
CREATE TABLE articles (
    article_id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL REFERENCES issues(issue_id),
    title TEXT NOT NULL, authors TEXT NOT NULL,
    start_page INTEGER NOT NULL, end_page INTEGER NOT NULL, doi TEXT NOT NULL UNIQUE,
    CHECK (end_page >= start_page)
);
CREATE TABLE bookshelf (
    journal_id TEXT PRIMARY KEY REFERENCES journals(journal_id),
    position INTEGER NOT NULL UNIQUE
);
CREATE TABLE saved_articles (
    article_id TEXT PRIMARY KEY REFERENCES articles(article_id),
    position INTEGER NOT NULL UNIQUE
);
CREATE TABLE notifications (
    notification_id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL UNIQUE REFERENCES issues(issue_id),
    read INTEGER NOT NULL DEFAULT 0 CHECK (read IN (0, 1))
);
CREATE INDEX articles_issue ON articles(issue_id);
CREATE INDEX issues_journal ON issues(journal_id);
"""


ARTICLE_SELECT = (
    "SELECT a.article_id, j.journal_id, j.title AS journal_title, j.issn, i.issue_id, i.volume, i.issue_number, "
    "i.year, a.title, a.authors, a.start_page, a.end_page, a.doi, "
    "EXISTS (SELECT 1 FROM saved_articles s WHERE s.article_id = a.article_id) AS saved "
    "FROM articles a JOIN issues i ON i.issue_id = a.issue_id JOIN journals j ON j.journal_id = i.journal_id"
)


def _article(row: sqlite3.Row, *, with_issn: bool = False) -> dict:
    article = {**dict(row), "authors": json.loads(row["authors"]), "saved": bool(row["saved"])}
    if not with_issn:  # the ISSN is only needed for citations, not in the Article response
        del article["issn"]
    return article


class NotFound(Exception):
    """The named journal, issue, article or notification does not exist (HTTP 404)."""


class Conflict(Exception):
    """The action repeats or contradicts the current state (HTTP 409)."""


class Store:
    def __init__(self, db_path: Path, seed_path: Path = DEFAULT_SEED):
        self.db_path = Path(db_path).resolve()
        self.seed_path = Path(seed_path).resolve()

    @contextmanager
    def connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            # Writes reserve the writer first so a check and its write are one atomic step.
            # Reads also run in one transaction, so every SELECT in a request sees the same state.
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create and seed an empty database; leave an existing one untouched."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as connection:
            tables = {r[0] for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            app_id = connection.execute("PRAGMA application_id").fetchone()[0]
            if tables:
                if app_id != APPLICATION_ID or not TABLES.issubset(tables):
                    raise RuntimeError(
                        f"{self.db_path} was not created by this service. Choose another POLYGATE_DB_FILE.")
                return  # Preserve user data across restarts and redeploys; never reseed.
            self._create_and_seed(connection)

    def reset(self) -> None:
        """Replace this service's data with the seed data. Refuses foreign databases."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as connection:
            tables = {r[0] for r in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables:
                if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                    raise RuntimeError(
                        f"{self.db_path} was not created by this service; refusing to reset it.")
                for name in ("notifications", "saved_articles", "bookshelf", "articles", "issues", "journals"):
                    connection.execute(f"DROP TABLE IF EXISTS {name}")
            self._create_and_seed(connection)

    def _create_and_seed(self, connection: sqlite3.Connection) -> None:
        seed = SeedData.model_validate(json.loads(self.seed_path.read_text(encoding="utf-8")))
        for statement in filter(None, (s.strip() for s in SCHEMA.split(";"))):
            connection.execute(statement)
        connection.executemany(
            "INSERT INTO journals VALUES (:journal_id, :title, :issn, :subject, :publisher)",
            [j.model_dump() for j in seed.journals])
        connection.executemany(
            "INSERT INTO issues VALUES (:issue_id, :journal_id, :volume, :issue_number, :year, "
            ":publication_date, :status)",
            [{**i.model_dump(), "publication_date": i.publication_date and i.publication_date.isoformat()}
             for i in seed.issues])
        connection.executemany(
            "INSERT INTO articles VALUES (:article_id, :issue_id, :title, :authors, :start_page, "
            ":end_page, :doi)",
            [{**a.model_dump(), "authors": json.dumps(a.authors)} for a in seed.articles])
        connection.executemany(
            "INSERT INTO bookshelf VALUES (:journal_id, :position)", [b.model_dump() for b in seed.bookshelf])
        connection.executemany(
            "INSERT INTO saved_articles VALUES (:article_id, :position)",
            [s.model_dump() for s in seed.saved_articles])
        connection.executemany(
            "INSERT INTO notifications VALUES (:notification_id, :issue_id, :read)",
            [{**n.model_dump(), "read": int(n.read)} for n in seed.notifications])
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        connection.execute("PRAGMA user_version = 1")

    def ping(self) -> None:
        with self.connection() as connection:
            connection.execute("SELECT 1 FROM journals LIMIT 1").fetchone()

    # ---- Journals ----

    def search_journals(self, q: str | None, subject: str | None, issn: str | None,
                        limit: int, offset: int) -> tuple[list[dict], int]:
        where, args = [], []
        if q is not None:
            where.append("instr(lower(j.title), lower(?)) > 0")
            args.append(q)
        if subject is not None:
            where.append("lower(j.subject) = lower(?)")
            args.append(subject)
        if issn is not None:
            where.append("j.issn = ?")
            args.append(issn)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connection() as c:
            total = c.execute(f"SELECT COUNT(*) FROM journals j {clause}", args).fetchone()[0]
            rows = c.execute(
                f"SELECT j.journal_id, j.title, j.issn, j.subject, "
                f"EXISTS (SELECT 1 FROM bookshelf b WHERE b.journal_id = j.journal_id) AS in_bookshelf "
                f"FROM journals j {clause} ORDER BY lower(j.title), j.journal_id LIMIT ? OFFSET ?",
                [*args, limit, offset]).fetchall()
        return [{**dict(r), "in_bookshelf": bool(r["in_bookshelf"])} for r in rows], total

    def get_journal(self, journal_id: str) -> dict:
        with self.connection() as c:
            journal = c.execute(
                "SELECT j.*, EXISTS (SELECT 1 FROM bookshelf b WHERE b.journal_id = j.journal_id) "
                "AS in_bookshelf FROM journals j WHERE j.journal_id = ?", (journal_id,)).fetchone()
            if journal is None:
                raise NotFound(f"Journal {journal_id} does not exist.")
            issues = c.execute(
                "SELECT i.issue_id, i.volume, i.issue_number, i.year, i.publication_date, i.status, "
                "(SELECT COUNT(*) FROM articles a WHERE a.issue_id = i.issue_id) AS article_count "
                "FROM issues i WHERE i.journal_id = ? "
                "ORDER BY i.year DESC, i.volume DESC, i.issue_number DESC", (journal_id,)).fetchall()
        return {**dict(journal), "in_bookshelf": bool(journal["in_bookshelf"]),
                "issues": [dict(i) for i in issues]}

    # ---- Articles ----

    def list_articles(self, journal_id: str, issue_id: str | None) -> list[dict]:
        with self.connection() as c:
            if c.execute("SELECT 1 FROM journals WHERE journal_id = ?", (journal_id,)).fetchone() is None:
                raise NotFound(f"Journal {journal_id} does not exist.")
            if issue_id is not None:
                issue = c.execute("SELECT journal_id FROM issues WHERE issue_id = ?", (issue_id,)).fetchone()
                if issue is None:
                    raise NotFound(f"Issue {issue_id} does not exist.")
                if issue["journal_id"] != journal_id:
                    raise NotFound(f"Issue {issue_id} does not belong to journal {journal_id}.")
            rows = c.execute(
                f"{ARTICLE_SELECT} WHERE i.journal_id = ? AND (? IS NULL OR i.issue_id = ?) "
                "ORDER BY i.year DESC, i.volume DESC, i.issue_number DESC, a.article_id",
                (journal_id, issue_id, issue_id)).fetchall()
        return [_article(r) for r in rows]

    # ---- Bookshelf ----

    BOOKSHELF_SELECT = (
        "SELECT j.journal_id, j.title, j.issn, j.subject, "
        "(SELECT COUNT(*) FROM notifications n JOIN issues i ON i.issue_id = n.issue_id "
        " WHERE i.journal_id = j.journal_id AND n.read = 0) AS unread_count "
        "FROM bookshelf b JOIN journals j ON j.journal_id = b.journal_id"
    )

    def _bookshelf_entry(self, c: sqlite3.Connection, journal_id: str) -> dict:
        return dict(c.execute(f"{self.BOOKSHELF_SELECT} WHERE b.journal_id = ?", (journal_id,)).fetchone())

    def list_bookshelf(self) -> list[dict]:
        """One statement, so the journals and their unread counts come from the same moment."""
        with self.connection() as c:
            return [dict(r) for r in c.execute(f"{self.BOOKSHELF_SELECT} ORDER BY b.position")]

    def add_to_bookshelf(self, journal_id: str) -> dict:
        with self.connection(write=True) as c:
            if c.execute("SELECT 1 FROM journals WHERE journal_id = ?", (journal_id,)).fetchone() is None:
                raise NotFound(f"Journal {journal_id} does not exist.")
            if c.execute("SELECT 1 FROM bookshelf WHERE journal_id = ?", (journal_id,)).fetchone():
                raise Conflict(f"Journal {journal_id} is already on the bookshelf.")
            c.execute("INSERT INTO bookshelf VALUES (?, (SELECT COALESCE(MAX(position), 0) + 1 FROM bookshelf))",
                      (journal_id,))
            return self._bookshelf_entry(c, journal_id)

    def remove_from_bookshelf(self, journal_id: str) -> None:
        with self.connection(write=True) as c:
            if c.execute("SELECT 1 FROM journals WHERE journal_id = ?", (journal_id,)).fetchone() is None:
                raise NotFound(f"Journal {journal_id} does not exist.")
            if c.execute("DELETE FROM bookshelf WHERE journal_id = ?", (journal_id,)).rowcount == 0:
                raise Conflict(f"Journal {journal_id} is not on the bookshelf.")

    # ---- Notifications ----

    NOTIFICATION_SELECT = (
        "SELECT n.notification_id, j.journal_id, j.title AS journal_title, i.issue_id, i.volume, "
        "i.issue_number, i.publication_date, n.read, "
        "(SELECT COUNT(*) FROM articles a WHERE a.issue_id = i.issue_id) AS article_count "
        "FROM notifications n JOIN issues i ON i.issue_id = n.issue_id "
        "JOIN journals j ON j.journal_id = i.journal_id "
        "JOIN bookshelf b ON b.journal_id = j.journal_id"  # join = visible only while followed
    )

    def list_notifications(self, status: str) -> tuple[list[dict], int]:
        with self.connection() as c:
            rows = c.execute(
                f"{self.NOTIFICATION_SELECT} ORDER BY i.publication_date DESC, n.notification_id").fetchall()
        items = [{**dict(r), "read": bool(r["read"])} for r in rows]
        unread = sum(not n["read"] for n in items)
        if status != "all":
            items = [n for n in items if n["read"] == (status == "read")]
        return items, unread

    def mark_notification_read(self, notification_id: str) -> dict:
        with self.connection(write=True) as c:
            row = c.execute(f"{self.NOTIFICATION_SELECT} WHERE n.notification_id = ?",
                            (notification_id,)).fetchone()
            if row is None:
                raise NotFound(f"Notification {notification_id} does not exist.")
            if row["read"]:
                raise Conflict(f"Notification {notification_id} is already read.")
            c.execute("UPDATE notifications SET read = 1 WHERE notification_id = ?", (notification_id,))
            return {**dict(row), "read": True}

    # ---- Saved articles ----

    def _get_article(self, c: sqlite3.Connection, article_id: str) -> dict:
        row = c.execute(f"{ARTICLE_SELECT} WHERE a.article_id = ?", (article_id,)).fetchone()
        if row is None:
            raise NotFound(f"Article {article_id} does not exist.")
        return _article(row)

    def list_saved_articles(self) -> list[dict]:
        with self.connection() as c:
            rows = c.execute(f"{ARTICLE_SELECT} JOIN saved_articles sv ON sv.article_id = a.article_id "
                             "ORDER BY sv.position").fetchall()
        return [_article(r) for r in rows]

    def save_article(self, article_id: str) -> dict:
        with self.connection(write=True) as c:
            self._get_article(c, article_id)
            if c.execute("SELECT 1 FROM saved_articles WHERE article_id = ?", (article_id,)).fetchone():
                raise Conflict(f"Article {article_id} is already saved.")
            c.execute("INSERT INTO saved_articles VALUES "
                      "(?, (SELECT COALESCE(MAX(position), 0) + 1 FROM saved_articles))", (article_id,))
            return self._get_article(c, article_id)

    def remove_saved_article(self, article_id: str) -> None:
        with self.connection(write=True) as c:
            self._get_article(c, article_id)
            if c.execute("DELETE FROM saved_articles WHERE article_id = ?", (article_id,)).rowcount == 0:
                raise Conflict(f"Article {article_id} is not saved.")

    def citation_source(self, article_id: str) -> dict:
        """Stored metadata of a saved article, for citation export."""
        with self.connection() as c:
            row = c.execute(
                f"{ARTICLE_SELECT} WHERE a.article_id = ?", (article_id,)).fetchone()
            if row is None:
                raise NotFound(f"Article {article_id} does not exist.")
            if not row["saved"]:
                raise Conflict(f"Article {article_id} is not saved.")
        return _article(row, with_issn=True)
