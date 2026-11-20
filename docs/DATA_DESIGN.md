# Data Design: BrowZine Mock

Companion to [API_DESIGN.md](API_DESIGN.md). Phase 2 specifies the data; Phase 3 generates `data/mock_data.json` and loads it into SQLite. All data is synthetic; journal titles, authors and DOIs (prefix `10.9999`) are fictional.

## Tables

| Table | Key columns |
|---|---|
| `journals` | `journal_id` PK, `title`, `issn`, `subject`, `publisher` |
| `issues` | `issue_id` PK, `journal_id` FK, `volume`, `issue_number`, `year`, `publication_date` (NULL when `in_press`), `status` (`published` / `in_press`) |
| `articles` | `article_id` PK, `issue_id` FK, `title`, `authors` (JSON list), `start_page`, `end_page`, `doi` |
| `bookshelf` | `journal_id` PK/FK, `position` (follow order) |
| `saved_articles` | `article_id` PK/FK, `position` (save order) |
| `notifications` | `notification_id` PK (`N-<issue_id>`), `issue_id` FK unique, `read` (0/1) |

The single user `U1` is a label in documentation, not a table. Visibility rule: a notification is returned only when its issue's journal is in `bookshelf`. Deleting from `bookshelf` never touches `notifications`.

## Seed counts and layout

- **10 journals** `J01`–`J10`, all in one discipline, Artificial Intelligence. The `subject` field is an AI sub-area: Artificial Intelligence (J01–J03), Computer Vision (J04–J05), Natural Language Processing (J06–J07), Robotics and Autonomous Systems (J08–J09), AI Ethics and Governance (J10). The journal count and the discipline are decided.
- **20 issues**: journal `Jn` owns `I(2n-1)` and `I(2n)`. Two are `in_press`: **I06** (J03) and **I14** (J07).
- **60 articles**: issue `Ik` owns `A(3k-2)`–`A(3k)`, so I05 holds A013–A015.
- **18 notifications**, one per published issue, all unread except `N-I01`.
- **Seeded bookshelf:** J01 and J04. **Seeded saved articles:** none.
- Fixed values for the worked example: J03 "Neural Computation Letters", ISSN `2049-3630`; J01 ISSN `1234-5679` (valid check digits); I05 = volume 12, number 3, 2026, published 2026-09-15; A013 "Spiking Network Models for Sensor Fusion", authors Chan, Wai Ming and Lee, Sze Yan, pages 101–115, DOI `10.9999/ncl.12.3.101`.
- Phase 3 generates the remaining ISSNs with valid check digits, and gives every article 1–3 authors with ASCII-only names so BibTeX keys stay simple.

On a fresh database the visible notifications are `N-I01` (read), `N-I02`, `N-I07`, `N-I08` (unread): `meta.unread_count` on `GET /notifications` is 3.

## Seed rows and the cases they exercise

| Case | Seed rows used | Expected |
|---|---|---|
| Search with no match | `q=zzz` | `200`, empty list |
| Follow a new journal | J03 | `201`; `N-I05` becomes visible, unread |
| Repeat follow | J01 | `409` |
| In-press exclusion | follow J03 (I06 is in press) | no `N-I06`; `GET /notifications` has no I06 entry |
| Mark read, then repeat | `N-I02` | `200`, then `409` |
| Notification of an unfollowed journal | `N-I03` (J02 not followed) | `404` |
| Unfollow and refollow | J04 | its notifications vanish, then return with the same read state |
| Unknown ID | J99, A999 | `404` |
| Malformed ID | `bad id!` | `422` |
| Save, repeat, export | A013 | `201`, `409`, `200` |
| Export unsaved | A001 | `409` |
| Bad format | `format=pdf` | `422` |

## Test sequence (fresh database)

| Step | Request | Expected | Saved data |
|---|---|---|---|
| 1 | `GET /journals?q=neural` | `200`, J03, `in_bookshelf: false` | none |
| 2 | `POST /bookshelf` J03 | `201`, `data.unread_count: 1` | J03 in bookshelf |
| 3 | `POST /bookshelf` J03 | `409` | unchanged |
| 4 | `GET /notifications?status=unread` | `200`; N-I02, N-I05, N-I07, N-I08; `meta.unread_count` 4 | none |
| 5 | `POST /notifications/N-I05/read` | `200`, `data.read: true` | N-I05 read |
| 6 | `POST /notifications/N-I05/read` | `409` | unchanged |
| 7 | `GET /journals/J03/articles?issue_id=I05` | `200`, A013–A015 | none |
| 8 | `POST /saved-articles` A013 | `201` | A013 saved |
| 9 | `POST /saved-articles` A013 | `409` | unchanged |
| 10 | `GET /saved-articles/A013/citation?format=bibtex` | `200`, BibTeX as in API_DESIGN | none |
| 11 | `GET /saved-articles/A013/citation?format=ris` | `200`, RIS as in API_DESIGN | none |
| 12 | `GET /saved-articles/A001/citation?format=ris` | `409` | none |
| 13 | `DELETE /bookshelf/J03` then `GET /notifications` | `204`; N-I05 gone from list | N-I05 still read in DB |

## Reset and persistence (for Phase 3)

Seed only when the database is empty; `reset --yes` recreates it. The database path comes from `POLYGATE_DB_FILE` (persistent volume `/data` on ceAI+).
