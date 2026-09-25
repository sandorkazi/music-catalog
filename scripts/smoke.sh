#!/usr/bin/env bash
# Smoke test: pytest + read-only CLI checks against real state. No writes.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"   # no-op once `pip install -e .` is done

python3 -m pytest tests/ -q
python3 -m music_catalog.cli --help >/dev/null
python3 -m music_catalog.cli gaps --compact >/dev/null
python3 -m music_catalog.cli publish --to both --dry-run >/dev/null
if python3 -m music_catalog.cli publish --to spotify >/dev/null 2>&1; then
  echo "FAIL: bare publish should be refused in v1" >&2; exit 1
fi
echo "smoke OK"
