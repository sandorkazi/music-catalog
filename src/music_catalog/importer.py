"""Tolerant import: Spotify export JSON / YouTube (yt-dlp) playlist JSON -> catalog store + report."""
from __future__ import annotations

import json
from pathlib import Path

from .store import add_track, ensure_artist, normalize_name, slug_for


def _spotify_track_item(node: dict, added_at=None, default_source="spotify") -> dict | None:
    """Normalize one Spotify track object (or playlist-item wrapper)."""
    if not isinstance(node, dict):
        return None
    t = node.get("track") if isinstance(node.get("track"), dict) else node
    if not isinstance(t, dict):
        return None
    title = t.get("name")
    artists = t.get("artists") or []
    if not title:
        return {"_unknown": True, "reason": "missing-title", "raw_id": t.get("id")}
    if not artists:
        return {"_unknown": True, "reason": "missing-artists", "title": title, "raw_id": t.get("id")}
    norm_artists = []
    for a in artists:
        if not isinstance(a, dict):
            continue
        name = a.get("name")
        if not name:
            continue
        aid = a.get("id") or f"local:{slug_for(name)}"
        norm_artists.append({"id": aid, "name": name})
    if not norm_artists:
        return {"_unknown": True, "reason": "missing-artists", "title": title, "raw_id": t.get("id")}
    album = t.get("album") or {}
    return {
        "track_id": t.get("id") or f"local:{slug_for(title)}-{slug_for(norm_artists[0]['name'])}",
        "title": title,
        "artists": norm_artists,
        "popularity": t.get("popularity", 0) or 0,
        "album": album.get("name") if isinstance(album, dict) else None,
        "added_at": node.get("added_at", added_at),
        "source": default_source,
        "url": (t.get("external_urls") or {}).get("spotify"),
    }


def iter_export_items(data) -> list[dict]:
    """Accept several export shapes; return per-track item dicts."""
    items: list[dict] = []
    if isinstance(data, dict) and isinstance(data.get("playlists"), list):
        for pl in data["playlists"]:
            for it in pl.get("tracks", []) or []:
                if isinstance(it, dict):
                    items.append(it)
        return items
    if isinstance(data, dict) and isinstance(data.get("tracks"), dict):
        return data["tracks"].get("items", []) or []
    if isinstance(data, dict) and isinstance(data.get("tracks"), list):
        return data["tracks"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return data["items"]
    raise ValueError("unrecognized export shape: top-level keys=" + ",".join(sorted(data.keys())) if isinstance(data, dict) else type(data).__name__)


def parse_export(path: str | Path, source: str = "spotify") -> tuple[list[dict], int]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    from .youtube import is_youtube_export, iter_yt_entries, yt_entry_to_item

    if is_youtube_export(data) or source == "youtube":
        raw = iter_yt_entries(data)
        parsed = [yt_entry_to_item(n) for n in raw]
        return [p for p in parsed if p is not None], len(raw)
    raw = iter_export_items(data)
    parsed = [_spotify_track_item(n, default_source=source) for n in raw]
    return [p for p in parsed if p is not None], len(raw)


def import_items(catalog: dict, review: dict, items: list[dict], source: str = "spotify") -> dict:
    report = {
        "seen": len(items),
        "added_artists": 0,
        "added_tracks": 0,
        "duplicate_tracks": 0,
        "capped_tracks": 0,
        "unknowns": 0,
        "pending_merges": 0,
    }
    for it in items:
        if it.get("_unknown"):
            report["unknowns"] += 1
            entry = {
                "title": it.get("title"),
                "reason": it.get("reason", "unknown"),
                "source": it.get("source", source),
                "spotify_id": it.get("raw_id") if source == "spotify" else None,
                "youtube_id": it.get("raw_id") if it.get("source", source) == "youtube" else None,
                "channel": it.get("channel"),
            }
            entry = {k: v for k, v in entry.items() if v is not None}
            if entry not in review["unknown"]:
                review["unknown"].append(entry)
            continue
        primary = it["artists"][0]
        for a in it["artists"]:
            _, created, pending = ensure_artist(catalog, review, a["id"], a["name"])
            if created:
                report["added_artists"] += 1
            if pending:
                report["pending_merges"] += 1
        # alias featured artists on the primary record for visibility
        prim_rec = next(a for a in catalog["artists"] if a["id"] == primary["id"])
        for feat in it["artists"][1:]:
            if normalize_name(feat["name"]) not in [normalize_name(x) for x in prim_rec.get("aliases", [])] and normalize_name(feat["name"]) != normalize_name(prim_rec["name"]):
                prim_rec.setdefault("aliases", []).append(feat["name"])
        track = {
            "id": it["track_id"],
            "artist_id": primary["id"],
            "title": it["title"],
            "source": it.get("source", source),
            "popularity": it.get("popularity", 0),
            "features": {},
            "pinned": False,
            "album": it.get("album"),
            "added_at": it.get("added_at"),
            "url": it.get("url"),
        }
        if it.get("video_title"):
            track["video_title"] = it["video_title"]
        if it.get("channel"):
            track["channel"] = it["channel"]
        outcome = add_track(catalog, track)
        if outcome == "added":
            report["added_tracks"] += 1
        elif outcome == "duplicate":
            report["duplicate_tracks"] += 1
        else:
            report["capped_tracks"] += 1
    report["pending_merges_total"] = len(review["pending_merges"])
    report["unknown_total"] = len(review["unknown"])
    return report
