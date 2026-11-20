#!/usr/bin/env bash
# Build the ceAI+ upload ZIP: only what the Dockerfile COPYs, with Dockerfile at the ZIP root.
# Usage: scripts/make_zip.sh [version]   (default 0.2.0) -> dist/browzine-mock-<version>.zip
set -euo pipefail
cd "$(dirname "$0")/.."
version="${1:-0.2.0}"
out="dist/browzine-mock-${version}.zip"
mkdir -p dist
rm -f "$out"
zip -X -q "$out" Dockerfile requirements.txt constraints.txt data/mock_data.json
zip -X -q "$out" browzine_mock/*.py
echo "Contents:"; unzip -Z1 "$out"
echo "Size: $(wc -c < "$out") bytes (limit 100 MiB)"
echo "SHA-256: $(shasum -a 256 "$out" | cut -d' ' -f1)"
