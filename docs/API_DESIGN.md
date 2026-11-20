# API Design: BrowZine Mock (Journals, Bookshelf, Notifications, Saved Articles, Citations)

**Status:** Phase 2 complete (reviewed 2026-11-11); response format revised 2026-11-19 (version 0.2.0).

This document is the API contract for the PolyGate BrowZine mock. All journals, issues, articles and notifications are synthetic. BrowZine's public Third Iron API documents journal, issue, subject, search and DOI/PMID lookup endpoints only. Every route and field below is **our own design**, modelled on BrowZine app behaviour, not a published BrowZine schema. Machine-readable form: [openapi.json](../openapi.json). Data and seed design: [DATA_DESIGN.md](DATA_DESIGN.md).

## Business tasks and shared APIs

| Task | What the user wants | API calls, in order |
|---|---|---|
| W1 Search for a journal | Find a journal and read its details. | Search journals → Get journal details |
| W2 Follow a journal | Put a journal on the bookshelf. | Search journals → Get journal details → Add to bookshelf → List bookshelf (→ Remove from bookshelf) |
| W3 Check updates | See new issues of followed journals. | List bookshelf → List notifications → Mark notification read |
| W4 Save an article | Keep an article in My Articles. | List articles by journal → Save article → List saved articles (→ Remove saved article) |
| W5 Export a citation | Get a BibTeX or RIS record. | List saved articles → Export citation |

Example journey: search "neural" → follow J03 → list notifications → mark `N-I05` read → list J03's articles → save `A013` → export its BibTeX.

| Capability | Endpoint | Used by |
|---|---|---|
| Search journals | `GET /journals` | W1, W2 |
| Get journal details | `GET /journals/{journal_id}` | W1, W2 |
| List articles by journal | `GET /journals/{journal_id}/articles` | W4, W5 |
| Add to bookshelf | `POST /bookshelf` | W2 |
| List bookshelf | `GET /bookshelf` | W2, W3 |
| Remove from bookshelf | `DELETE /bookshelf/{journal_id}` | W2 |
| List notifications | `GET /notifications` | W3 |
| Mark notification read | `POST /notifications/{notification_id}/read` | W3 |
| Save article | `POST /saved-articles` | W4 |
| List saved articles | `GET /saved-articles` | W4, W5 |
| Remove saved article | `DELETE /saved-articles/{article_id}` | W4 |
| Export citation | `GET /saved-articles/{article_id}/citation` | W5 |
| Health check | `GET /health` | deployment |

Base URL locally: `http://127.0.0.1:8000`. Each capability is implemented once; W-tasks reuse it.

## Shared rules

- **One mock user.** The service has one fixed user (label `U1`), one bookshelf and one saved-articles list. There is no `user_id` parameter. There is no authentication; nothing identifies a caller.
- **Identifiers** contain 1–64 ASCII letters, digits, underscores or hyphens and start with a letter or digit (regex `^[A-Za-z0-9][A-Za-z0-9_-]*$`). Formats: journals `J01`–`J10`, issues `I01`–`I20`, articles `A001`–`A060`, notifications `N-<issue_id>` (for example `N-I05`).
- **Dates** use `YYYY-MM-DD` (Hong Kong time). **ISSN** uses `NNNN-NNNC`.
- **Unknown fields** in a request body or query string are rejected with `422`.
- **Status codes** (stated once, used everywhere):

| Code | Meaning here |
|---|---|
| `200` / `201` / `204` | Success; created; success with no body (deletes). |
| `404` | The named journal, issue, article or notification does not exist (or, for a notification, is not visible because its journal is not on the bookshelf). |
| `409` | The action repeats or contradicts the current state: following a followed journal, saving a saved article, marking a read notification read, removing something that is not on the list, exporting an article that is not saved. No data changes. |
| `422` | Invalid input: malformed ID, bad query value, missing or unknown field. |

- **Response format:** see the next section. Every JSON success uses `{"data": ..., "meta": ...}`; every error uses RFC 9457 problem details.
- **No clock.** Nothing depends on the current time. Notifications come from seeded issues; no background job creates them.
- **Mutations are atomic.** Each write checks state and saves in one transaction.

## Response format

Decided 2026-11-19. Modelled on [JSON:API](https://jsonapi.org/format/#document-top-level) (one top-level `data` member for a single resource or a list) and [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) (problem details, with one entry per invalid field).

**Success (every JSON `200`/`201`):** a single resource or a list goes in `data`. `meta` is present only when there is something to say about the result: paging on `GET /journals` (`total`, `limit`, `offset`), and `unread_count` on `GET /notifications`. Lists are never bare arrays; an empty result is `{"data": []}` with `200`.

```json
{
  "data": [
    {"journal_id": "J03", "title": "Neural Computation Letters", "issn": "2049-3630",
     "subject": "Artificial Intelligence", "in_bookshelf": false}
  ],
  "meta": {"total": 1, "limit": 20, "offset": 0}
}
```

**Error (every `4xx`):** `Content-Type: application/problem+json`, with `type` (always `about:blank`), `title` (the HTTP status phrase), `status`, `detail` (a human-readable sentence) and `instance` (the request path). A `422` adds `errors`: one entry per invalid input, with `detail` and either `pointer` (a JSON Pointer into the request body, `#` for the whole body) or `parameter` (a query or path parameter name).

```http
POST /bookshelf
{"journal_id": "bad id", "x": 1}
```

```json
{
  "type": "about:blank", "title": "Unprocessable Content", "status": 422,
  "detail": "The request has invalid input; see errors.", "instance": "/bookshelf",
  "errors": [
    {"detail": "String should match pattern '^[A-Za-z0-9][A-Za-z0-9_-]*$'", "pointer": "#/journal_id"},
    {"detail": "Extra inputs are not permitted", "pointer": "#/x"}
  ]
}
```

A `404` or `409` has the same fields without `errors`, for example `{"type": "about:blank", "title": "Conflict", "status": 409, "detail": "Article A001 is not saved.", "instance": "/saved-articles/A001/citation"}`. This applies to the citation route too: its errors are `application/problem+json`, not text.

**Not wrapped, on purpose:** a successful citation export is `text/plain` (the BibTeX or RIS record itself); deletes return `204` with no body; `GET /health` returns `{"status": "ok"}` because the platform probe reads it.

`openapi.json` documents every `4xx` as `application/problem+json` (`Problem`, and `ValidationProblem` for `422`). `tests/test_contract.py` sends one real request per documented status and checks that the `Content-Type` and body shape match.

## Notification model (decided: simple)

BrowZine tells users when a new issue of a bookshelf journal is available, and tracks unread state per article or issue. The mock simplifies this:

- Every **published** issue has exactly one notification (`N-<issue_id>`). Issues with `status: "in_press"` have none, matching the rule that only issue-assigned articles notify.
- A notification is **visible** only while its journal is on the bookshelf.
- Read state is stored **per notification** (not per article). *This differs from BrowZine and is a deliberate simplification.*
- Unfollowing hides a journal's notifications and keeps their read state; following again restores them. *This is a mock decision: no source describes unfollow behaviour.*
- `unread_count` on a bookshelf entry is the number of unread visible notifications for that journal.
- Email digests (daily/weekly) and push notifications are out of scope.

These simplifications are accepted; no further walkthrough is planned.

## 1. Search journals

**Purpose:** Find journals by title, subject or ISSN.

**Request:** `GET /journals` with optional query parameters:

| Input | Example | Meaning |
|---|---|---|
| `q` | `neural` | Case-insensitive substring of the title. |
| `subject` | `Artificial Intelligence` | Exact subject, case-insensitive. |
| `issn` | `2049-3630` | Exact ISSN. |
| `limit` | `20` | 1–50, default 20. |
| `offset` | `0` | Default 0. |

Filters combine with AND. No filter lists all journals.

**Output:** `200` with `data`, a list of journals (each: `journal_id`, `title`, `issn`, `subject`, `in_bookshelf`), and `meta` with `total` (matches before paging), `limit` and `offset`. Sorted by title.

**Rules:** No match returns an empty list. An invalid `issn`, `limit` outside 1–50, negative `offset` or unknown parameter returns `422`.

```http
GET /journals?q=neural
```

```json
{
  "data": [
    {"journal_id": "J03", "title": "Neural Computation Letters", "issn": "2049-3630",
     "subject": "Artificial Intelligence", "in_bookshelf": false}
  ],
  "meta": {"total": 1, "limit": 20, "offset": 0}
}
```

## 2. Get journal details

**Purpose:** Show one journal and its issues.

**Request:** `GET /journals/{journal_id}`

**Output:** `200` with `data`: `journal_id`, `title`, `issn`, `subject`, `publisher`, `in_bookshelf` and `issues`, a list ordered newest first. Each issue has `issue_id`, `volume`, `issue_number`, `year`, `publication_date`, `status` (`published` or `in_press`) and `article_count`.

**Rules:** `404` for an unknown journal; `422` for a malformed ID.

```json
{
  "data": {
    "journal_id": "J03", "title": "Neural Computation Letters", "issn": "2049-3630",
    "subject": "Artificial Intelligence", "publisher": "PolyGate Synthetic Press",
    "in_bookshelf": false,
    "issues": [
      {"issue_id": "I06", "volume": 12, "issue_number": 4, "year": 2026,
       "publication_date": null, "status": "in_press", "article_count": 3},
      {"issue_id": "I05", "volume": 12, "issue_number": 3, "year": 2026,
       "publication_date": "2026-09-15", "status": "published", "article_count": 3}
    ]
  }
}
```

## 3. List articles by journal

**Purpose:** Discover article IDs and basic metadata so an article can be saved or cited. This is the only article-discovery route; there is no separate browsing module.

**Request:** `GET /journals/{journal_id}/articles`, optional query `issue_id`.

**Output:** `200` with `data`, a list of articles ordered by issue (newest first) then article ID. Each article: `article_id`, `journal_id`, `journal_title`, `issue_id`, `volume`, `issue_number`, `year`, `title`, `authors` (list of "Surname, Given"), `start_page`, `end_page`, `doi`, `saved`.

**Rules:** `404` for an unknown journal, an unknown issue, or an issue that belongs to a different journal. `422` for malformed IDs. Articles in `in_press` issues are listed and can be saved.

## 4. Add to bookshelf

**Purpose:** Follow a journal.

**Request:** `POST /bookshelf`, body `{"journal_id": "J03"}` (required, only field).

**Output:** `201` with `data`, the bookshelf entry: `journal_id`, `title`, `issn`, `subject`, `unread_count`.

**Rules:** `404` unknown journal; `409` already on the bookshelf; `422` invalid body.

## 5. List bookshelf

**Request:** `GET /bookshelf`

**Output:** `200` with `data`, the entries as above, in the order followed (seeded entries first). An empty bookshelf returns `{"data": []}`. The journals and their `unread_count` values come from one database read, so they always describe the same moment, even while other requests change the bookshelf or notifications.

## 6. Remove from bookshelf

**Request:** `DELETE /bookshelf/{journal_id}`

**Output:** `204`, no body. The journal's notifications become invisible (see the notification model).

**Rules:** `404` unknown journal; `409` journal is not on the bookshelf; `422` malformed ID.

## 7. List notifications

**Purpose:** See new issues of followed journals.

**Request:** `GET /notifications`, optional `status` = `unread`, `read` or `all` (default `all`).

**Output:** `200` with `data`, the notifications, and `meta.unread_count` (unread visible notifications, regardless of the filter). Each notification: `notification_id`, `journal_id`, `journal_title`, `issue_id`, `volume`, `issue_number`, `publication_date`, `article_count`, `read`. Ordered by `publication_date` descending, then `notification_id`.

**Rules:** Only notifications for bookshelf journals appear. `422` for another `status` value.

```json
{
  "data": [
    {"notification_id": "N-I05", "journal_id": "J03", "journal_title": "Neural Computation Letters",
     "issue_id": "I05", "volume": 12, "issue_number": 3, "publication_date": "2026-09-15",
     "article_count": 3, "read": false}
  ],
  "meta": {"unread_count": 1}
}
```

## 8. Mark notification read

**Request:** `POST /notifications/{notification_id}/read`, no body.

**Output:** `200` with `data`, the updated notification (`read: true`).

**Rules:** `404` for an unknown notification or one whose journal is not on the bookshelf; `409` if it is already read; `422` for a malformed ID or **any request body** (even `{}` or `{"read": false}`); the notification stays unchanged. Marking read is permanent; there is no "mark unread".

## 9. Save article

**Request:** `POST /saved-articles`, body `{"article_id": "A013"}`.

**Output:** `201` with `data`, the article (as in API 3, `saved: true`).

**Rules:** `404` unknown article; `409` already saved; `422` invalid body. The article's journal need not be on the bookshelf.

## 10. List saved articles

**Request:** `GET /saved-articles`

**Output:** `200` with `data`, the saved articles in the order saved. `{"data": []}` when none.

## 11. Remove saved article

**Request:** `DELETE /saved-articles/{article_id}`

**Output:** `204`. **Rules:** `404` unknown article; `409` not currently saved.

## 12. Export citation

**Request:** `GET /saved-articles/{article_id}/citation?format=bibtex` (or `ris`). `format` is required.

**Output:** `200`, `Content-Type: text/plain; charset=utf-8`, the record built only from stored metadata.

**Rules:** `404` unknown article; `409` article not saved; `422` for a missing or other `format`.

BibTeX: entry type `@article`; key = lowercase ASCII first-author surname + year + lowercase article ID (`chan2026a013`); fields in this order: `author` (joined by ` and `), `title`, `journal`, `year`, `volume`, `number`, `pages` (`start--end`), `doi`, `issn`. Two-space indent, one field per line, closing `}`.

```bibtex
@article{chan2026a013,
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
```

RIS: tags in this order, `TAG  - value` (two spaces before the hyphen), one `AU` per author, ended by `ER  - `: `TY` (`JOUR`), `AU`, `TI`, `JO`, `PY`, `VL`, `IS`, `SP`, `EP`, `DO`, `SN`, `ER`.

```
TY  - JOUR
AU  - Chan, Wai Ming
AU  - Lee, Sze Yan
TI  - Spiking Network Models for Sensor Fusion
JO  - Neural Computation Letters
PY  - 2026
VL  - 12
IS  - 3
SP  - 101
EP  - 115
DO  - 10.9999/ncl.12.3.101
SN  - 2049-3630
ER  - 
```

## 13. Health check

`GET /health` returns `200` `{"status": "ok"}`. Used by the ceAI+ deployment.

**Rejection case for endpoints without inputs** (`GET /bookshelf`, `GET /saved-articles`, `GET /health`): any query parameter returns `422`, per the unknown-field rule. The service enforces this explicitly (FastAPI ignores unknown query parameters by default); `tests/test_search.py` covers it.

**Public path** (Phase 5): behind the ceAI+ gateway the app is served under `/<username>/<app-name>/`. The gateway strips that prefix and sends `X-Forwarded-Prefix`; the app uses it only to build `/docs` and `servers` links (`browzine_mock/prefix.py`). Endpoint paths in this document do not change.

**Repeated query parameters** (added in Phase 5): a parameter given more than once (`?limit=1&limit=2`) returns `422` on every endpoint, so a request never has an ambiguous meaning.

## Acceptance criteria mapping

| Phase 1 criterion | Where it is defined |
|---|---|
| 1. W1–W5 run end to end | Tasks table; API 1–12 |
| 2. Success and rejection case per endpoint | Each API section; test sequence in DATA_DESIGN.md |
| 3. Repeats return `409` | Shared rules; APIs 4, 6, 8, 9, 11 |
| 4. Unknown IDs `404`, malformed input `422` | Shared rules |
| 5. Notifications only for followed journals, read state persists | Notification model; APIs 7, 8 |
| 6. Valid BibTeX/RIS matching stored metadata | API 12 |

## Open decisions

- Notification model (trigger per issue, read state per notification, unfollow hides but keeps state): **decided on 2026-11-11 to keep it simple.** Not observed in live BrowZine; accepted as a mock simplification.
- No API authentication until the team confirms.
- Search covers title substring, subject and ISSN: decided.
- All journals belong to one discipline, Artificial Intelligence; `subject` is an AI sub-area.
- Decided: `409` for unsaved export and removal, `404` for a notification whose journal is not followed.
