#!/usr/bin/env bash
# Sync helper for the data repo (default sibling checkout).
# Usage: scripts/sync-data.sh [pull|push|status] [--data-dir DIR]
set -euo pipefail

DATA_DIR_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/../music-catalog-masu"
DATA_DIR="${MUSIC_CATALOG_DATA_DIR:-$DATA_DIR_DEFAULT}"
CMD="${1:-status}"

for arg in "$@"; do
  case "$arg" in
    --data-dir=*) DATA_DIR="${arg#--data-dir=}" ;;
  esac
done

if [[ ! -d "$DATA_DIR/.git" ]]; then
  echo "cloning data repo into $DATA_DIR ..." >&2
  git clone git@github.com:sandorkazi/music-catalog-masu.git "$DATA_DIR"
fi

case "$CMD" in
  pull) git -C "$DATA_DIR" pull --ff-only ;;
  push) git -C "$DATA_DIR" push ;;
  status) git -C "$DATA_DIR" status --short --branch ;;
  *) echo "usage: $0 [pull|push|status] [--data-dir DIR]" >&2; exit 2 ;;
esac
