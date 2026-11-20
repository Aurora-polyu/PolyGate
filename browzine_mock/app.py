"""PolyGate BrowZine mock API: the 12 business routes and /health.

Response format (docs/API_DESIGN.md, "Response format"):
- JSON success: {"data": <object or list>, "meta": {...}}; meta only where it carries something.
- Every 4xx: RFC 9457 problem details as application/problem+json; 422 adds "errors", one per input.
- Exceptions: citation export is text/plain, deletes are 204 with no body, /health is {"status": "ok"}.
"""

from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Annotated, Literal
import os
import sqlite3

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .citations import to_bibtex, to_ris
from .models import (
    AddBookshelfRequest, ArticleList, ArticleResponse, Bookshelf, BookshelfEntryResponse, Identifier, IdPath,
    Issn, JournalIdPath, JournalList, JournalResponse, NotificationList, NotificationResponse, Problem,
    SaveArticleRequest, ValidationProblem,
)
from .prefix import ForwardedPrefixMiddleware
from .store import DEFAULT_DB, DEFAULT_SEED, Conflict, NotFound, Store

PROBLEM_JSON = "application/problem+json"


def public_path(request: Request) -> str:
    """The request path as the client sees it, including the ceAI+ public prefix (root_path) if any."""
    root, path = request.scope.get("root_path", ""), request.scope["path"]
    return path if path.startswith(root) else root + path


def problem_response(request: Request, status: int, detail: str, errors: list[dict] | None = None,
                     headers: dict | None = None):
    body = {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status, "detail": detail,
            "instance": public_path(request)}
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON, headers=headers)


def field_error(error: dict) -> dict:
    """Map one FastAPI/pydantic error to {"detail", "pointer"} (body) or {"detail", "parameter"} (query, path)."""
    where, *rest = error["loc"]
    if where == "body":
        if error.get("type") == "json_invalid":
            rest = []
        return {"detail": error["msg"], "pointer": "#" + "".join(f"/{part}" for part in rest)}
    return {"detail": error["msg"], "parameter": str(rest[0]) if rest else where}


def problem(description: str) -> dict:
    """A documented 4xx; openapi() below sets its content to application/problem+json."""
    return {"description": description}


def reject_unknown_query(request: Request) -> None:
    """Shared rule: any query parameter the route does not declare is a 422, not silently ignored."""
    route = request.scope.get("route")
    if route is None:
        return
    known, pending = set(), [route.dependant]
    while pending:  # include query parameters declared by sub-dependencies
        dependant = pending.pop()
        known.update(p.alias or p.name for p in dependant.query_params)
        pending.extend(dependant.dependencies)
    names = [name for name, _ in request.query_params.multi_items()]
    errors = [
        {"type": "extra_forbidden", "loc": ("query", name), "msg": "Extra inputs are not permitted",
         "input": request.query_params[name]}
        for name in dict.fromkeys(names) if name not in known]
    errors += [  # a parameter given twice (?limit=1&limit=2) is ambiguous, so reject it
        {"type": "duplicate_parameter", "loc": ("query", name), "msg": "Query parameter given more than once",
         "input": request.query_params.getlist(name)}
        for name in dict.fromkeys(names) if name in known and names.count(name) > 1]
    if errors:
        raise RequestValidationError(errors)


async def reject_body(request: Request) -> None:
    """For routes that take no body: any body (even {}) is an unknown field, so 422 before anything changes."""
    body = await request.body()
    if body:
        raise RequestValidationError([{"type": "extra_forbidden", "loc": ("body",),
                                       "msg": "This endpoint takes no request body",
                                       "input": body.decode("utf-8", "replace")}])


def create_app(db_path: Path | None = None, seed_path: Path | None = None) -> FastAPI:
    path = db_path if db_path is not None else Path(os.getenv("POLYGATE_DB_FILE", DEFAULT_DB))
    store = Store(Path(path), Path(seed_path) if seed_path is not None else DEFAULT_SEED)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store.initialize()
        yield

    application = FastAPI(
        title="PolyGate BrowZine Mock API",
        version="0.2.0",
        description=(
            "A synthetic mock of BrowZine-style journal search, bookshelf, notifications, saved articles "
            "and citation export. All data is fictional. There is one mock user and no authentication."
        ),
        lifespan=lifespan,
        dependencies=[Depends(reject_unknown_query)],
    )
    application.add_middleware(ForwardedPrefixMiddleware)
    application.state.store = store

    @application.exception_handler(NotFound)
    async def not_found_handler(request: Request, exc: NotFound):
        return problem_response(request, 404, str(exc))

    @application.exception_handler(Conflict)
    async def conflict_handler(request: Request, exc: Conflict):
        return problem_response(request, 409, str(exc))

    @application.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = [field_error(e) for e in exc.errors()]
        return problem_response(request, 422, "The request has invalid input; see errors.",
                                errors)

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):  # unknown route, 405
        return problem_response(request, exc.status_code, str(exc.detail), headers=exc.headers)  # keeps Allow

    def openapi():
        """Every 4xx is documented as application/problem+json, and 422 is listed on every operation
        (unknown query parameters are rejected everywhere). FastAPI would otherwise use the route's own
        media type, e.g. text/plain for the citation route's errors."""
        schema = FastAPI.openapi(application)  # FastAPI's own builder: keeps servers, tags and caching
        if "ValidationProblem" in schema.get("components", {}).get("schemas", {}):
            return schema  # already adjusted
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in (Problem, ValidationProblem):
            model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
            components.update(model_schema.pop("$defs", {}))
            components[model.__name__] = model_schema
        for name in ("HTTPValidationError", "ValidationError"):
            components.pop(name, None)
        for item in schema["paths"].values():
            for operation in item.values():
                responses = operation["responses"]
                responses["422"] = {
                    "description": "Invalid input: malformed ID, bad query value, missing or unknown field.",
                    "content": {PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/ValidationProblem"}}}}
                for code, response in responses.items():
                    if code.startswith("4") and code != "422":
                        response["content"] = {
                            PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/Problem"}}}
        return schema

    application.openapi = openapi

    @application.get(
        "/health", operation_id="health_check", summary="Health check", tags=["Operations"],
        responses={503: {"description": "The database cannot be read."}},
        description="Platform probe; kept as plain {\"status\": \"ok\"}, outside the data envelope.",
    )
    def health():
        try:
            store.ping()
        except (sqlite3.Error, OSError):
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ok"}

    @application.get(
        "/journals", operation_id="search_journals", summary="Search journals", tags=["Journals"],
        description="Find journals by title substring, subject or ISSN. Filters combine with AND; "
                    "no filter lists all. Sorted by title.",
        response_model=JournalList,
    )
    def search_journals(
        q: Annotated[str | None, Query(min_length=1, max_length=120, examples=["neural"],
                                       description="Case-insensitive title substring.")] = None,
        subject: Annotated[str | None, Query(min_length=1, max_length=120,
                                             examples=["Artificial Intelligence"],
                                             description="Exact subject, case-insensitive.")] = None,
        issn: Annotated[Issn | None, Query(examples=["2049-3630"])] = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        journals, total = store.search_journals(q, subject, issn, limit, offset)
        return {"data": journals, "meta": {"total": total, "limit": limit, "offset": offset}}

    @application.get(
        "/journals/{journal_id}", operation_id="get_journal_details", summary="Get journal details",
        tags=["Journals"], response_model=JournalResponse,
        responses={404: problem("The journal does not exist.")},
    )
    def get_journal_details(journal_id: JournalIdPath):
        return {"data": store.get_journal(journal_id)}

    @application.get(
        "/journals/{journal_id}/articles", operation_id="list_articles_by_journal",
        summary="List articles by journal", tags=["Journals"], response_model=ArticleList,
        responses={404: problem("The journal or issue does not exist, or the issue is in another journal.")},
        description="The only article-discovery route: article IDs and basic metadata, newest issue first.",
    )
    def list_articles_by_journal(
        journal_id: JournalIdPath,
        issue_id: Annotated[Identifier | None, Query(description="Only articles of this issue.")] = None,
    ):
        return {"data": store.list_articles(journal_id, issue_id)}

    @application.get(
        "/bookshelf", operation_id="list_bookshelf", summary="List bookshelf", tags=["Bookshelf"],
        response_model=Bookshelf,
    )
    def list_bookshelf():
        return {"data": store.list_bookshelf()}

    @application.post(
        "/bookshelf", operation_id="add_to_bookshelf", summary="Add to bookshelf", tags=["Bookshelf"],
        status_code=201, response_model=BookshelfEntryResponse,
        responses={404: problem("The journal does not exist."), 409: problem("Already on the bookshelf.")},
    )
    def add_to_bookshelf(body: AddBookshelfRequest):
        return {"data": store.add_to_bookshelf(body.journal_id)}

    @application.delete(
        "/bookshelf/{journal_id}", operation_id="remove_from_bookshelf", summary="Remove from bookshelf",
        tags=["Bookshelf"], status_code=204, response_class=Response,
        responses={404: problem("The journal does not exist."), 409: problem("Not on the bookshelf.")},
    )
    def remove_from_bookshelf(journal_id: JournalIdPath):
        store.remove_from_bookshelf(journal_id)
        return Response(status_code=204)

    @application.get(
        "/notifications", operation_id="list_notifications", summary="List notifications",
        tags=["Notifications"], response_model=NotificationList,
        description="New published issues of bookshelf journals. Newest first.",
    )
    def list_notifications(status: Literal["unread", "read", "all"] = "all"):
        items, unread = store.list_notifications(status)
        return {"data": items, "meta": {"unread_count": unread}}

    @application.post(
        "/notifications/{notification_id}/read", operation_id="mark_notification_read",
        summary="Mark notification read", tags=["Notifications"], response_model=NotificationResponse,
        description="Takes no request body; any body is rejected with 422 and nothing changes.",
        responses={404: problem("The notification does not exist or its journal is not on the bookshelf."),
                   409: problem("Already read.")},
        dependencies=[Depends(reject_body)],
    )
    def mark_notification_read(notification_id: IdPath):
        return {"data": store.mark_notification_read(notification_id)}

    @application.get(
        "/saved-articles", operation_id="list_saved_articles", summary="List saved articles",
        tags=["Saved articles"], response_model=ArticleList,
    )
    def list_saved_articles():
        return {"data": store.list_saved_articles()}

    @application.post(
        "/saved-articles", operation_id="save_article", summary="Save article", tags=["Saved articles"],
        status_code=201, response_model=ArticleResponse,
        responses={404: problem("The article does not exist."), 409: problem("Already saved.")},
    )
    def save_article(body: SaveArticleRequest):
        return {"data": store.save_article(body.article_id)}

    @application.delete(
        "/saved-articles/{article_id}", operation_id="remove_saved_article", summary="Remove saved article",
        tags=["Saved articles"], status_code=204, response_class=Response,
        responses={404: problem("The article does not exist."), 409: problem("Not saved.")},
    )
    def remove_saved_article(article_id: IdPath):
        store.remove_saved_article(article_id)
        return Response(status_code=204)

    @application.get(
        "/saved-articles/{article_id}/citation", operation_id="export_citation", summary="Export citation",
        tags=["Citations"], response_class=PlainTextResponse,
        responses={200: {"content": {"text/plain": {"schema": {"type": "string"}}},
                         "description": "Citation text"},
                   404: problem("The article does not exist."), 409: problem("The article is not saved.")},
        description="BibTeX or RIS record built only from stored metadata. BibTeX key: lowercase "
                    "first-author surname + year + lowercase article ID.",
    )
    def export_citation(article_id: IdPath, format: Literal["bibtex", "ris"]):
        article = store.citation_source(article_id)
        text = to_bibtex(article) if format == "bibtex" else to_ris(article)
        return PlainTextResponse(text, media_type="text/plain; charset=utf-8")

    return application
