"""Data-dir resolution: code repo never owns state; the data repo does."""
from __future__ import annotations

import os
from pathlib import Path

DATA_REPO_SSH = "git@github.com:sandorkazi/music-catalog-masu.git"
STATE_FILES = ("catalog.json", "review.json")


def resolve_data_dir(explicit: str | os.PathLike | None = None) -> Path:
    """Return the data-repo checkout dir. First existing wins.

    1. ``explicit`` arg or ``$MUSIC_CATALOG_DATA_DIR``
    2. sibling ``../music-catalog-masu`` next to this repo
    Raises FileNotFoundError if none exists.
    """
    candidates: list[Path] = []
    env = os.environ.get("MUSIC_CATALOG_DATA_DIR")
    if explicit is not None:
        candidates.append(Path(explicit))
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    # src/music_catalog/data.py -> repo root = parents[2]
    repo_root = here.parents[2]
    candidates.append(repo_root.parent / "music-catalog-masu")
    for c in candidates:
        if c.is_dir():
            return c
    raise FileNotFoundError(
        "music-catalog data checkout not found; set MUSIC_CATALOG_DATA_DIR "
        f"or clone {DATA_REPO_SSH} next to the code repo. Tried: {candidates}"
    )


def state_path(filename: str, data_dir: str | os.PathLike | None = None) -> Path:
    """Path to a state file inside the data repo (e.g. catalog.json)."""
    base = resolve_data_dir(data_dir)
    return base / "state" / filename
