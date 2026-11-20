# PolyGate BrowZine Mock API — Handover

(`<username>` stands for the ceAI+ account username, left out of the public repository.)

Written 2026-11-11; updated 2026-11-20 for version 0.2.0. Status: version 0.2.0 deployed and running on ceAI+.

## 1. Deployment record

| Item | Value |
|---|---|
| Service | PolyGate BrowZine Mock API (FastAPI + SQLite, synthetic data only) |
| App name | `browzine-mock` (ceAI+ student console, `https://polygate.polylink.org`) |
| Public URL | `https://apps.polylink.org/<username>/browzine-mock/` |
| Swagger docs | `https://apps.polylink.org/<username>/browzine-mock/docs` |
| Health check | `GET /health` returns `200 {"status":"ok"}` |
| Version | `0.2.0`, deployed 2026-11-20 (first public commit) |
| Source ZIP | `browzine-mock-0.2.0.zip`, SHA-256 `2eeced9eb5f54ea6f52fa0e35a32d32b1d62716d008c02d5f3496613a91306a8` (built by `scripts/make_zip.sh`) |
| Base image | `python:3.12-alpine`, `linux/amd64`, runs as UID/GID 65532 |
| Image digest | `sha256:fccbfe7c74becc028ccd0ed724551e00e011a35536214df3bc5b4dcde362f83f` (Approved: no Critical or Unknown findings) |
| Previous version | `0.1.0`: ZIP SHA-256 `9c39a48566d696abd4f420b1b309e995886d0a73abce0f50de0a8701304c609e`, image `sha256:fe320289214e953666eb43e48d71f3fb11202278bf37ebf406dd8bbc1375a8c7` (kept for rollback) |
| Port / health path | `8000` / `/health` |
| Resources | CPU 250 m request, 1000 m limit; memory 512 MiB; 1 replica |
| Storage | volume `browzine-data`, 1 GiB, mounted at `/data`; database `/data/browzine.sqlite3` (`POLYGATE_DB_FILE`) |
| Secrets | none |
| Authentication | none (one mock user `U1`; `user_id` is only a label) |

Operations: 12 business endpoints plus `/health` (see `docs/API_DESIGN.md`, `openapi.json`). The live `/openapi.json` includes the public path under `servers`. Since 0.2.0, JSON successes are `{"data": ..., "meta": ...}` and every 4xx is RFC 9457 `application/problem+json` (API_DESIGN.md, "Response format"); clients written for 0.1.0 must be updated.

## 2. How to use it

- Browse and try the API at the Swagger URL above, or run the acceptance journey: `python scripts/demo.py --base-url https://apps.polylink.org/<username>/browzine-mock`. It works on the live data as it is, with no reset, and can be run any number of times. It follows a journal that is not on the bookshelf and saves an article that is not saved, checks the 409/422 cases, then undoes both. It fails unless the bookshelf, notifications and saved articles end exactly as they started. It never marks a notification read, because that cannot be undone. Run it while nobody else is changing the data: its cleanup removes the follow and the save it made, even if someone made the same change meanwhile. The script sends its own `User-Agent`, because the gateway rejects Python's default one (`403`, error 1010). If the gateway drops a connection, the script sends a `GET` or `DELETE` once more (safe to repeat) and stops on a dropped `POST` with a hint to check the data.
- Calls from other tools should send a normal `User-Agent` header for the same reason.
- Public-path support: the gateway removes `/<username>/<app-name>` and sends `X-Forwarded-Prefix`; `browzine_mock/prefix.py` uses it so `/docs` works. API routes themselves are unchanged (`/health`, `/journals`, ...).

## 3. Redeploy or update

1. Change the code and run the tests: `.venv/bin/pytest` (122 tests).
2. `scripts/make_zip.sh` builds `dist/browzine-mock-<version>.zip` from only the files the Dockerfile copies.
3. Console → **Source ZIP** → "Use my Dockerfile" → upload the ZIP → Queue build; wait for Succeeded.
4. **My images** → wait for **Approved**. Rejected means Critical or Unknown findings; open View report and fix the base image or packages.
5. **Overview** → for a running app use **Update image**; for a stopped or failed app use **Deploy image**. Choose the new digest (check it matches the build) and confirm. Wait for **Running**.
6. Check `/health`, `/docs` and the demo script on the public URL. Run the demo twice; both runs must pass and the data must stay as it was.

The database is on the volume, so a redeploy keeps all data and never reseeds (the seed loads only into an empty database).

## 4. Reset the data to the seed

Only needed to recover from bad data. Acceptance checks do not need it (see section 2).

The console has no shell, so `reset --yes` cannot be run. **This deletes all data on the volume.** Tested on ceAI+ on 2026-11-11 (about 5 minutes end to end):

1. Overview → **Stop** the app and confirm; wait for Stopped.
2. **Edit storage** → switch persistent storage off → Save storage (this removes the binding; files stay on the volume).
3. **Volumes** → **Delete** `browzine-data`, type the volume name to confirm; wait until the volume disappears (status Deleting, then gone, about 30 seconds). The name cannot be reused before that.
4. **Volumes** → request `browzine-data` again, 1 GiB; wait for Ready (Reserved, then Ready, about 1 minute).
5. **Edit storage** → switch persistent storage on, choose the new volume, mount path `/data` → Save storage.
6. **Deploy image** → choose the current Approved digest (check it) → Deploy image. The empty database is reseeded from `data/mock_data.json`.
7. Check: `GET /saved-articles` is empty, `GET /bookshelf` lists J01 and J04, and unread notifications are N-I02, N-I07 and N-I08.

Keep `data/mock_data.json` and `scripts/generate_seed.py` in the repository: volumes are single-copy pilot storage with daily external backups.

## 5. Monitoring and incident runbook

- **Status:** Overview shows Queued, Deploying, Running, Stopped or Failed. **Logs** shows the latest 200 lines, events and resource usage; use "Previous attempt" after a restart.
- **Quota** (per account): 2 apps, 4 Pods, 4 GiB memory, 2,000 m CPU requests, 4,000 m CPU limits, 2 volumes, 10 GiB storage. Stopped apps and drafts still count; Stop does not release quota.

| Symptom | Likely cause and action |
|---|---|
| Build failed | Source ZIP → View log; check the Dockerfile and requirements |
| Image Rejected | View report: Critical or Unknown findings block deployment (the original Debian 13 base failed on 5 OpenSSL CVEs; Alpine passes) |
| Crash loop, `PermissionError` on `/app/...` | App files unreadable by UID 65532; the Dockerfile's `chmod -R a+rX /app` prevents it |
| `connection refused` | App port must match the listening port (8000) and bind `0.0.0.0`; Edit port, then Deploy image |
| `Read-only file system` or cannot create `/data` | Persistent storage must be on with the volume mounted at `/data`; write only to `/data` or `/tmp` |
| `403` error 1010 from a script | Set a custom `User-Agent` |
| Swagger loads but "Try it out" gives 404 | Reopen the URL from Open app; the prefix must come from `X-Forwarded-Prefix` |
| ceAI+ site will not open | Check VPN settings and routing |
| Script gets `RemoteDisconnected` / connection closed without response | The gateway sometimes drops a connection (seen 2026-11-20; the app logs never show the request). Retry the request; `scripts/demo.py` retries a dropped `GET` or `DELETE` once |

For help, give the administrator the app name, the time and the error, never passwords or keys.

## 6. Verification evidence

- **Version 0.2.0 (2026-11-20):**
  - Local: 122 tests pass. The image built from the ZIP (`linux/amd64`) ran read-only as UID 65532 with a `/tmp` tmpfs and a volume. `/health`, prefixed `/docs` and the 404/405/409/422 problem+json responses all work. The demo ran four times, on seed data and on changed data, with the data unchanged. Data survived a restart and a new container on the same volume. Trivy was not run locally for 0.2.0; the ceAI+ scan approved the image.
  - On ceAI+: build Succeeded, image Approved, app Running on the new digest (no restart recorded). Live checks: `/health`, version `0.2.0` and `servers` with the public path; `/docs` loads `/<username>/browzine-mock/openapi.json`; 404 problem+json with the public path in `instance`; `PUT /bookshelf` gives 405; mark-read with `{"read": false}` gives 422 and N-I02 stays unread; exporting an unsaved article gives a 409 problem+json (not text/plain). Data kept through the update: bookshelf J01 and J04, 3 unread notifications, 0 saved articles.
  - Demo on live data: 4 of 4 runs passed after adding the retry, and the data was identical before and after. Before the retry, 2 of 4 runs stopped on a gateway connection drop, with the data still unchanged. A separate run of 60 plain requests had no drops (median 1.05 s).
- **Version 0.1.0 (2026-11-11):**
  - Local: 110 tests pass (success and rejection cases, repeated actions, data consistency, OpenAPI contract, public path); image verified as UID 65532 with a read-only filesystem, `/tmp` tmpfs and a volume; Trivy: 0 Critical, 0 Unknown.
  - On ceAI+: build Succeeded, image Approved, app Running; public `/health` and `/docs` work; `/docs` loads `/<username>/browzine-mock/openapi.json`; the demo journey passes end to end; error cases return `404` (unknown journal), `409` (repeated follow), `422` (unknown or repeated query parameter, unknown body field); saved article A013 survived a stop and redeploy.
  - The reset procedure in section 4 was run on 2026-11-11 and the live data is back in seed state (0 saved articles, bookshelf J01 and J04, unread N-I02, N-I07, N-I08).
- Not tested: load tests, concurrent writers during the demo, and failure-recovery beyond a stop, a redeploy and the reset.

## 7. Isolation and safety statement

All data is fictional (1 user label, 10 journals, 20 issues, 60 articles). The deployment holds no secrets, production credentials, production routes or personal data, and has no authentication. Anyone with the URL can read and change the mock data.

## 8. Known limitations and open items

- One mock user and one bookshelf; only journal search is paged; BibTeX special characters are not escaped (the seed has none); SQLite serialises writes.
- The demo leaves the data unchanged, so it never needs a reset. It needs a journal that is not on the bookshelf and has an unsaved article (it exits with a message otherwise).
- The ceAI+ gateway sometimes closes a connection without a response; clients should retry safe requests.
- To confirm with the supervising team: whether a GHCR image is required (the ZIP build route was used), API authentication, logging and revocation expectations, deadlines, and the preferred handover format.
