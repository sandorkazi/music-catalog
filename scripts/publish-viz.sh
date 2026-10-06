#!/usr/bin/env bash
# Publish the artist-similarity browser into the DATA repo.
#
# The live site lives in the data repo (docs/graph.json + docs/index.html),
# generated natively from that repo's own state/catalog.json. The generator
# itself stays in this (code) repo.
#
# Usage (from this repo root):
#   bash scripts/publish-viz.sh            # render + commit in data repo
#   bash scripts/publish-viz.sh --check     # validate freshness only (exit 1 if stale)
#   bash scripts/publish-viz.sh --no-commit # render only, skip the data-repo commit
set -euo pipefail

CODE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${MUSIC_CATALOG_DATA_DIR:-$(cd "$CODE_DIR" && pwd)/../music-catalog-masu}"
CHECK=0
COMMIT=1

for arg in "$@"; do
  case "$arg" in
    --check) CHECK=1 ;;
    --no-commit) COMMIT=0 ;;
    --data-dir=*) DATA_DIR="${arg#--data-dir=}" ;;
  esac
done

if [[ ! -d "$DATA_DIR/.git" ]]; then
  echo "error: data checkout not found at $DATA_DIR" >&2
  exit 2
fi

run_catalog() {
  PYTHONPATH="$CODE_DIR/src" python3 -m music_catalog.cli \
    --data-dir "$DATA_DIR" "$@"
}

if [[ "$CHECK" == 1 ]]; then
  run_catalog viz --out-dir "$DATA_DIR/docs" --check
  exit $?
fi

run_catalog viz --out-dir "$DATA_DIR/docs"
run_catalog viz --out-dir "$DATA_DIR/docs" --check

if [[ "$COMMIT" == 1 ]]; then
  git -C "$DATA_DIR" add docs/graph.json docs/index.html
  if git -C "$DATA_DIR" diff --cached --quiet; then
    echo "site already up to date, nothing to commit."
  else
    graph=$(PYTHONPATH="$CODE_DIR/src" python3 -c \
      "import json; g=json.load(open('$DATA_DIR/docs/graph.json')); print(f\"{len(g['nodes'])} nodes/{len(g['edges'])} edges\")")
    git -C "$DATA_DIR" commit -m "viz: refresh Pages browser ($graph)" -- docs/graph.json docs/index.html
    echo "committed in $DATA_DIR. Push + ensure Pages serves docs/ (Settings -> Pages -> Deploy from branch -> docs/)."
  fi
fi
