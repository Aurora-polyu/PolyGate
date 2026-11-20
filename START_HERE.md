# Start here

PolyGate BrowZine Mock API: a FastAPI + SQLite mock of BrowZine (journal search, bookshelf, notifications, saved articles, citation export) with synthetic data, deployed on ceAI+.

Read in this order:

1. **[docs/GLOSSARY.md](docs/GLOSSARY.md)**: the project's words. You *follow* a journal and *save* an article; use the glossary terms everywhere.
2. **[docs/API_DESIGN.md](docs/API_DESIGN.md)**: the API contract, including the "Response format" (`data`/`meta`, RFC 9457 errors) and the status codes. [openapi.json](openapi.json) is the machine-readable form.
3. **[docs/DATA_DESIGN.md](docs/DATA_DESIGN.md)**: tables, seed data and the test sequence.
4. **[docs/HANDOVER.md](docs/HANDOVER.md)**: what is deployed on ceAI+, and how to redeploy, reset and troubleshoot it.

Quickstart (Python 3.11 or later):

```bash
./start.sh                     # create .venv, install, serve on http://127.0.0.1:8000/docs
.venv/bin/pytest               # run the tests
python scripts/demo.py         # acceptance demo against the running service; leaves the data unchanged
```
