"""File-backed artist/track store. JSON in the data repo is source of truth."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .data import resolve_data_dir, state_path

CATALOG_FILE = "catalog.json"
REVIEW_FILE = "review.json"
SCHEMA_VERSION = 1
TRACKS_PER_ARTIST_CAP = 5

_ws = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    return _ws.sub(" ", (name or "").strip()).casefold()


def slug_for(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize_name(name)).strip("-")
    return slug or "unknown"


def empty_catalog() -> dict:
    return {"artists": [], "tracks": [], "version": SCHEMA_VERSION}


def empty_review() -> dict:
    return {"pending_merges": [], "unknown": [], "version": SCHEMA_VERSION}


def load_json(path: Path, default: dict) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return default
    if not isinstance(data, dict):
        return default
    data.setdefault("version", SCHEMA_VERSION)
    return data


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_catalog(data_dir=None) -> tuple[dict, Path]:
    path = state_path(CATALOG_FILE, data_dir)
    data = load_json(path, empty_catalog())
    data.setdefault("artists", [])
    data.setdefault("tracks", [])
    return data, path


def load_review(data_dir=None) -> tuple[dict, Path]:
    path = state_path(REVIEW_FILE, data_dir)
    data = load_json(path, empty_review())
    data.setdefault("pending_merges", [])
    data.setdefault("unknown", [])
    return data, path


def find_artist(catalog: dict, artist_id: str) -> dict | None:
    for a in catalog["artists"]:
        if a.get("id") == artist_id:
            return a
    return None


def find_artist_by_name(catalog: dict, name: str) -> dict | None:
    norm = normalize_name(name)
    for a in catalog["artists"]:
        if normalize_name(a.get("name", "")) == norm:
            return a
        if norm in [normalize_name(x) for x in a.get("aliases", [])]:
            return a
    return None


def ensure_artist(catalog: dict, review: dict, artist_id: str, name: str) -> tuple[dict, bool, bool]:
    """Return (artist, created, merge_pending).

    Never silently merges: same normalized name under a different id
    creates a separate entry + a pending_merge candidate for user review.
    """
    existing = find_artist(catalog, artist_id)
    if existing is not None:
        return existing, False, False
    artist = {"id": artist_id, "name": name, "aliases": [], "status": "ok"}
    catalog["artists"].append(artist)
    clash = find_artist_by_name(catalog, name)
    merge_pending = False
    if clash is not None and clash is not artist:
        merge_pending = True
        entry = {"candidate_ids": sorted([clash["id"], artist_id]), "reason": "same-name-different-id"}
        if entry not in review["pending_merges"]:
            review["pending_merges"].append(entry)
    return artist, True, merge_pending


def artist_track_ids(catalog: dict, artist_id: str) -> list[str]:
    return [t["id"] for t in catalog["tracks"] if t.get("artist_id") == artist_id]


def add_track(catalog: dict, track: dict) -> str:
    """Add a track dict. Returns: 'added' | 'duplicate' | 'capped'.

    Enforces cap 5/artist keeping highest popularity.
    """
    for t in catalog["tracks"]:
        if t.get("id") == track["id"]:
            return "duplicate"
    mine = [t for t in catalog["tracks"] if t.get("artist_id") == track["artist_id"]]
    if len(mine) >= TRACKS_PER_ARTIST_CAP:
        weakest = min(mine, key=lambda t: (t.get("popularity", 0), t.get("id", "")))
        if track.get("popularity", 0) <= weakest.get("popularity", 0):
            return "capped"
        catalog["tracks"].remove(weakest)
    catalog["tracks"].append(track)
    return "added"
