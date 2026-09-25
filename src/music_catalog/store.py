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


def artist_track_count(catalog: dict, artist_id: str) -> int:
    return sum(1 for t in catalog["tracks"] if t.get("artist_id") == artist_id)


def merge_artists(catalog: dict, review: dict, keep_id: str, drop_id: str) -> dict:
    """Merge drop_id into keep_id (explicit, user-approved only).

    Moves tracks (pinned + highest popularity survive the cap of 5),
    unions aliases, removes the dropped record and stale pending entries.
    """
    if keep_id == drop_id:
        raise ValueError("keep_id and drop_id are identical")
    keep = find_artist(catalog, keep_id)
    drop = find_artist(catalog, drop_id)
    if keep is None:
        raise KeyError(f"unknown artist id: {keep_id}")
    if drop is None:
        raise KeyError(f"unknown artist id: {drop_id}")
    summary = {"keep": keep_id, "drop": drop_id, "moved_tracks": 0, "capped_tracks": [], "added_aliases": []}
    for t in catalog["tracks"]:
        if t.get("artist_id") == drop_id:
            t["artist_id"] = keep_id
            summary["moved_tracks"] += 1
    mine = [t for t in catalog["tracks"] if t.get("artist_id") == keep_id]
    # pinned tracks survive; then highest popularity; stable by id
    mine.sort(key=lambda t: (bool(t.get("pinned")), t.get("popularity", 0), t.get("id", "")), reverse=True)
    for extra in mine[TRACKS_PER_ARTIST_CAP:]:
        catalog["tracks"].remove(extra)
        summary["capped_tracks"].append(extra["id"])
    known = {normalize_name(keep.get("name", ""))} | {normalize_name(x) for x in keep.get("aliases", [])}
    for name in [drop.get("name", "")] + list(drop.get("aliases", [])):
        if name and normalize_name(name) not in known:
            keep.setdefault("aliases", []).append(name)
            known.add(normalize_name(name))
            summary["added_aliases"].append(name)
    catalog["artists"].remove(drop)
    before = len(review.get("pending_merges", []))
    review["pending_merges"] = [e for e in review.get("pending_merges", []) if drop_id not in e.get("candidate_ids", [])]
    summary["cleared_pending"] = before - len(review["pending_merges"])
    return summary


def dismiss_merge(review: dict, id1: str, id2: str) -> bool:
    """Drop a pending-merge candidate without merging (distinct artists)."""
    want = sorted([id1, id2])
    before = len(review.get("pending_merges", []))
    review["pending_merges"] = [e for e in review.get("pending_merges", []) if sorted(e.get("candidate_ids", [])) != want]
    return len(review["pending_merges"]) < before


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
