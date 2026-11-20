"""Seed-data models and API response models."""

from datetime import date
from typing import Annotated, Literal

from fastapi import Path
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
Identifier = Annotated[str, StringConstraints(pattern=ID_PATTERN, max_length=64)]
Issn = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}-[0-9]{3}[0-9X]$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def issn_is_valid(issn: str) -> bool:
    digits = issn.replace("-", "")
    total = sum((10 if c == "X" else int(c)) * w for c, w in zip(digits, range(8, 0, -1)))
    return total % 11 == 0


class JournalSeed(Strict):
    journal_id: Identifier
    title: str = Field(min_length=1)
    issn: Issn
    subject: str = Field(min_length=1)
    publisher: str = Field(min_length=1)


class IssueSeed(Strict):
    issue_id: Identifier
    journal_id: Identifier
    volume: int = Field(ge=1)
    issue_number: int = Field(ge=1)
    year: int
    publication_date: date | None
    status: Literal["published", "in_press"]

    @model_validator(mode="after")
    def date_matches_status(self):
        if (self.status == "in_press") != (self.publication_date is None):
            raise ValueError(f"{self.issue_id}: only in_press issues have no publication_date")
        return self


class ArticleSeed(Strict):
    article_id: Identifier
    issue_id: Identifier
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1, max_length=3)
    start_page: int = Field(ge=1)
    end_page: int = Field(ge=1)
    doi: str = Field(pattern=r"^10\.9999/\S+$")

    @model_validator(mode="after")
    def valid_pages_and_ascii(self):
        if self.end_page < self.start_page:
            raise ValueError(f"{self.article_id}: end_page before start_page")
        if not all(a.isascii() for a in self.authors):
            raise ValueError(f"{self.article_id}: author names must be ASCII")
        return self


class BookshelfSeed(Strict):
    journal_id: Identifier
    position: int = Field(ge=1)


class SavedArticleSeed(Strict):
    article_id: Identifier
    position: int = Field(ge=1)


class NotificationSeed(Strict):
    notification_id: Identifier
    issue_id: Identifier
    read: bool


class SeedData(Strict):
    journals: list[JournalSeed]
    issues: list[IssueSeed]
    articles: list[ArticleSeed]
    bookshelf: list[BookshelfSeed]
    saved_articles: list[SavedArticleSeed]
    notifications: list[NotificationSeed]

    @model_validator(mode="after")
    def cross_references(self):
        journals = {j.journal_id for j in self.journals}
        issues = {i.issue_id: i for i in self.issues}
        articles = {a.article_id for a in self.articles}
        for table, ids in (("journal", [j.journal_id for j in self.journals]),
                           ("issue", [i.issue_id for i in self.issues]),
                           ("article", [a.article_id for a in self.articles]),
                           ("DOI", [a.doi for a in self.articles]),
                           ("ISSN", [j.issn for j in self.journals])):
            if len(ids) != len(set(ids)):
                raise ValueError(f"Duplicate {table} in seed data")
        for j in self.journals:
            if not issn_is_valid(j.issn):
                raise ValueError(f"{j.journal_id}: invalid ISSN check digit {j.issn}")
        for i in self.issues:
            if i.journal_id not in journals:
                raise ValueError(f"{i.issue_id}: unknown journal {i.journal_id}")
        for a in self.articles:
            if a.issue_id not in issues:
                raise ValueError(f"{a.article_id}: unknown issue {a.issue_id}")
        for b in self.bookshelf:
            if b.journal_id not in journals:
                raise ValueError(f"Bookshelf references unknown journal {b.journal_id}")
        for s in self.saved_articles:
            if s.article_id not in articles:
                raise ValueError(f"Saved list references unknown article {s.article_id}")
        seen = set()
        for n in self.notifications:
            issue = issues.get(n.issue_id)
            if issue is None:
                raise ValueError(f"{n.notification_id}: unknown issue {n.issue_id}")
            if n.notification_id != f"N-{n.issue_id}":
                raise ValueError(f"{n.notification_id}: must be N-<issue_id>")
            if issue.status != "published":
                raise ValueError(f"{n.notification_id}: in-press issues have no notification")
            seen.add(n.issue_id)
        missing = {i for i, issue in issues.items() if issue.status == "published"} - seen
        if missing:
            raise ValueError(f"Published issues without a notification: {sorted(missing)}")
        return self


# ---- API models (Phase 4) ----

JournalIdPath = Annotated[str, Path(pattern=ID_PATTERN, max_length=64, description="Journal ID, e.g. J03.")]


class JournalSummary(Strict):
    journal_id: Identifier
    title: str
    issn: Issn
    subject: str
    in_bookshelf: bool


class PageMeta(Strict):
    total: int = Field(ge=0, description="Matches before paging.")
    limit: int
    offset: int


class JournalList(Strict):
    data: list[JournalSummary]
    meta: PageMeta


class Issue(Strict):
    issue_id: Identifier
    volume: int
    issue_number: int
    year: int
    publication_date: date | None = Field(description="null while status is in_press.")
    status: Literal["published", "in_press"]
    article_count: int


class JournalDetail(Strict):
    journal_id: Identifier
    title: str
    issn: Issn
    subject: str
    publisher: str
    in_bookshelf: bool
    issues: list[Issue] = Field(description="Newest first.")


class FieldError(Strict):
    detail: str
    pointer: str | None = Field(None, description="JSON Pointer into the request body, e.g. #/journal_id.")
    parameter: str | None = Field(None, description="Name of the query or path parameter.")


class Problem(BaseModel):
    """RFC 9457 problem details, sent as application/problem+json for every 4xx."""
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str


class ValidationProblem(Problem):
    errors: list[FieldError] = Field(description="One entry per invalid input.")


class Article(Strict):
    article_id: Identifier
    journal_id: Identifier
    journal_title: str
    issue_id: Identifier
    volume: int
    issue_number: int
    year: int
    title: str
    authors: list[str]
    start_page: int
    end_page: int
    doi: str
    saved: bool


class ArticleList(Strict):
    data: list[Article]


class ArticleResponse(Strict):
    data: Article


class AddBookshelfRequest(Strict):
    journal_id: Identifier


class BookshelfEntry(Strict):
    journal_id: Identifier
    title: str
    issn: Issn
    subject: str
    unread_count: int = Field(ge=0)


class Bookshelf(Strict):
    data: list[BookshelfEntry]


class BookshelfEntryResponse(Strict):
    data: BookshelfEntry


IdPath = Annotated[str, Path(pattern=ID_PATTERN, max_length=64)]


class Notification(Strict):
    notification_id: Identifier
    journal_id: Identifier
    journal_title: str
    issue_id: Identifier
    volume: int
    issue_number: int
    publication_date: date
    article_count: int
    read: bool


class NotificationMeta(Strict):
    unread_count: int = Field(ge=0, description="Unread visible notifications, regardless of the filter.")


class NotificationList(Strict):
    data: list[Notification]
    meta: NotificationMeta


class NotificationResponse(Strict):
    data: Notification


class SaveArticleRequest(Strict):
    article_id: Identifier


class JournalResponse(Strict):
    data: JournalDetail
