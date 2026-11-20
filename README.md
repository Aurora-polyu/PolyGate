# PolyGate BrowZine Mock API

Python + FastAPI + SQLite mock of BrowZine with synthetic data.

> Unofficial mock for a PolyU PolyGate student project. Not affiliated with or endorsed by Third Iron or BrowZine; all journals, articles and users are synthetic.

New here? Read [START_HERE.md](START_HERE.md) first; the project's terms are in [docs/GLOSSARY.md](docs/GLOSSARY.md). See `docs/API_DESIGN.md` for the contract and `docs/DATA_DESIGN.md` for the data.

**Status:** Stage 1 deployed on ceAI+, version 0.2.0: tests, demo script, deployment checks and public path support (`X-Forwarded-Prefix`) are done. All 12 business endpoints plus `/health` are live; see `tests/` (122 tests).

**Deployed (ceAI+, version 0.2.0 since 2026-11-20; first deployed 2026-11-11):** <https://apps.polylink.org/<username>/browzine-mock/docs> (app `browzine-mock`, port 8000, volume `browzine-data` at `/data`). Build the upload ZIP with `scripts/make_zip.sh`. Live checks passed: `/health`, `/docs`, the demo script (repeatable, data unchanged), problem+json 404/405/409/422 cases, data surviving a stop and redeploys, and the volume reset. Handover: `docs/HANDOVER.md`.

## Run locally (Python 3.11 or later)

```bash
./start.sh                     # macOS / Linux: creates .venv, installs, serves on 127.0.0.1:8000
.\start.ps1                    # Windows PowerShell
```

Then open <http://127.0.0.1:8000/docs> and <http://127.0.0.1:8000/health>.

| Command | Effect |
|---|---|
| `./start.sh serve --port 8000` | Start the API (default). |
| `./start.sh reset --yes` | Delete all changes and restore the seed data. Refused without `--yes`. |
| `./start.sh export-openapi` | Write the live schema to `openapi.live.json` (the reviewed `openapi.json` is never overwritten). |
| `.venv/bin/pytest` | Run the tests. |
| `python scripts/demo.py [--base-url URL]` | Run the acceptance journey against a running service, locally or at `https://apps.polylink.org/<username>/<app-name>`. Works on any data, can be repeated, and leaves the data unchanged. |

## Data

- `data/mock_data.json` holds the seed: 1 user label (`U1`), 10 journals, 20 issues, 60 articles, 18 notifications, bookshelf J01 and J04.
- Regenerate it with `python scripts/generate_seed.py`; the output is deterministic.
- The seed loads into SQLite only when the database is empty, so restarts and redeploys never overwrite or duplicate records.
- `POLYGATE_DB_FILE` sets the database path (default `data/browzine.sqlite3`; `/data/browzine.sqlite3` in the container).

## Docker (linux/amd64)

```bash
docker build --platform linux/amd64 -t browzine-mock .
docker run --rm -p 8000:8000 --user 65532:65532 --read-only --tmpfs /tmp -v browzine-data:/data browzine-mock
```

The container listens on `0.0.0.0:8000` and writes only to `/data` and `/tmp`. The platform runs apps as UID/GID 65532, so the mounted volume must be writable by that user.

## Known limitations

- One mock user (`U1`) and one bookshelf; no authentication.
- Synthetic data only; notifications are derived from seeded issues, not real-time events.
- Only `GET /journals` is paged; other lists return everything (the data set is small).
- Citation export does not escape BibTeX special characters (`&`, `%`, `_`, `{`, `}`); the seed contains none, and the API cannot add articles. A test guards this.
- SQLite allows one writer at a time; concurrent writes are serialised (20 parallel follows of one journal give one `201` and nineteen `409`).
- A parameter given twice, or an unknown parameter, is rejected with `422`.
