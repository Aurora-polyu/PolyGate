#!/bin/sh
# Create a virtual environment on first run, install dependencies, then run the service.
# Usage: ./start.sh [serve|reset --yes|export-openapi] [--port N]
set -eu
cd "$(dirname "$0")"
PYTHON_CMD="${PYTHON:-python3}"
if [ ! -x .venv/bin/python ]; then
  "$PYTHON_CMD" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'
  "$PYTHON_CMD" -m venv .venv
fi
.venv/bin/python -m pip --disable-pip-version-check install -q -r requirements-dev.txt
exec .venv/bin/python -m browzine_mock "$@"
