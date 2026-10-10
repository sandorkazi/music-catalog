"""Dual-source track consolidation: one track, refs on both Spotify and YouTube.

Model (schema v3, additive): a track is a source-agnostic entity. Its
per-source presence lives in ``track["sources"]``::

    {"spotify": {"id": ..., "url": ...},
     "youtube": {"id": ..., "url": ..., "video_title": ..., "channel": ...}}

The legacy ``track["source"]`` (first-seen origin) is kept for
compatibility; ``sources`` is the authority for coverage questions.
v1/v2 state migrates in memory (persisted on next write), like tags.

Rules: same artist + same normalized title = same track. An import from
the second source *links* (attaches its ref) instead of adding a
duplicate. Near-matches never auto-merge — they surface as
``needs_review`` for ``catalog link``.
"""
from __future__ import annotations

import difflib
import re

SOURCES = ("spotify", "youtube")

_FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with)\s+.*$", re.IGNORECASE)
_FEAT_PAREN_RE = re.compile(
    r"\s*[\(\[][^()\[\]]*(?:feat\.?|ft\.?|featuring|with)\b[^()\[\]]*[\)\]]",
    re.IGNORECASE)


def normalize_track_title(title: str) -> str:
    """Comparison key: feat mentions stripped, whitespace/case folded.

    ``Wasabi (feat. X)`` and ``Wasabi`` are the same track; ``Hit`` vs
    ``Hit (Remix)`` are not (bracket content other than feat is kept).
    """
    from .store import normalize_name

    t = _FEAT_PAREN_RE.sub("", title or "")
    t = _FEAT_RE.sub("", t).strip()
    return normalize_name(t)


def ensure_sources(track: dict) -> dict:
    """Fill ``track["sources"]`` from legacy fields if missing. Idempotent."""
    sources = track.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        track["sources"] = sources
    legacy = track.get("source")
    if legacy and legacy not in sources:
        ref: dict = {"id": track.get("id")}
        if track.get("url"):
            ref["url"] = track["url"]
        if legacy == "youtube":
            for k in ("video_title", "channel"):
                if track.get(k):
                    ref[k] = track[k]
        sources[legacy] = ref
    return sources


def migrate_track_sources(catalog: dict) -> int:
    """Schema v2 -> v3: ensure every track has a ``sources`` map. Idempotent."""
    touched = 0
    for t in catalog.get("tracks", []):
        before = dict(t.get("sources", {}) or {})
        ensure_sources(t)
        if t.get("sources", {}) != before:
            touched += 1
    if catalog.get("version", 1) < 3:
        catalog["version"] = 3
    return touched


def track_source_names(track: dict) -> set[str]:
    """Source names present on a track (migrates legacy ``source`` on read)."""
    sources = track.get("sources")
    if isinstance(sources, dict) and sources:
        return set(sources)
    legacy = track.get("source")
    return {legacy} if legacy else set()


def track_has_source(track: dict, source: str) -> bool:
    return source in track_source_names(track)


def source_ref(track: dict, source: str) -> dict | None:
    sources = track.get("sources")
    if isinstance(sources, dict):
        ref = sources.get(source)
        return ref if isinstance(ref, dict) else None
    if track.get("source") == source:
        return {"id": track.get("id"), "url": track.get("url")}
    return None


def build_ref(source: str, external_id: str, url: str | None = None,
              video_title: str | None = None, channel: str | None = None) -> dict:
    ref: dict = {"id": external_id}
    if url:
        ref["url"] = url
    if source == "youtube":
        if video_title:
            ref["video_title"] = video_title
        if channel:
            ref["channel"] = channel
    return ref


def attach_source(track: dict, source: str, ref: dict) -> bool:
    """Attach a source ref. Returns True when newly attached."""
    ensure_sources(track)
    if source in track["sources"]:
        return False
    track["sources"][source] = dict(ref)
    # fill top-level conveniences when missing
    if not track.get("url") and ref.get("url"):
        track["url"] = ref["url"]
    if source == "youtube":
        for k in ("video_title", "channel"):
            if not track.get(k) and ref.get(k):
                track[k] = ref[k]
    if isinstance(ref.get("popularity"), (int, float)):
        track["popularity"] = max(track.get("popularity", 0) or 0, ref["popularity"])
    return True


def detach_source(track: dict, source: str) -> bool:
    sources = track.get("sources")
    if isinstance(sources, dict) and source in sources:
        del sources[source]
        return True
    return False


def find_exact_linkable(catalog: dict, artist_id: str, title: str,
                        exclude_id: str | None = None) -> dict | None:
    """Same-artist track with equal normalized title (exact only, never fuzzy)."""
    want = normalize_track_title(title)
    for t in catalog.get("tracks", []):
        if t.get("artist_id") != artist_id or t.get("id") == exclude_id:
            continue
        if normalize_track_title(t.get("title", "")) == want:
            return t
    return None


def _prefer_dst(a: dict, b: dict) -> tuple[dict, dict]:
    """Canonical survivor: prefer a non-youtube id (stable Spotify ids win)."""
    a_yt = str(a.get("id", "")).startswith("youtube:")
    b_yt = str(b.get("id", "")).startswith("youtube:")
    if a_yt and not b_yt:
        return b, a
    return a, b


def merge_track_into(catalog: dict, dst: dict, src: dict) -> str:
    """Fold ``src`` refs/metadata into ``dst``, drop ``src``. Returns absorbed id."""
    ensure_sources(dst)
    ensure_sources(src)
    for name, ref in src.get("sources", {}).items():
        if name not in dst["sources"]:
            dst["sources"][name] = ref
    dst["popularity"] = max(dst.get("popularity", 0) or 0, src.get("popularity", 0) or 0)
    dst["pinned"] = bool(dst.get("pinned")) or bool(src.get("pinned"))
    if not dst.get("url") and src.get("url"):
        dst["url"] = src["url"]
    for k in ("album", "added_at", "video_title", "channel"):
        if not dst.get(k) and src.get(k):
            dst[k] = src[k]
    for k in ("genres", "instruments", "features"):
        if not dst.get(k) and src.get(k):
            dst[k] = src[k]
    absorbed = src["id"]
    catalog["tracks"].remove(src)
    return absorbed


def consolidate_artist(catalog: dict, artist_id: str) -> dict:
    """Exact-only same-title merge within one artist. Returns {merged, pairs}.

    Only merges when the absorbed track brings a source the survivor
    lacks — same-source duplicates (two videos, two Spotify editions)
    are kept as separate tracks so no ref is ever dropped.
    """
    by_key: dict[str, list[dict]] = {}
    for t in catalog.get("tracks", []):
        if t.get("artist_id") == artist_id:
            by_key.setdefault(normalize_track_title(t.get("title", "")), []).append(t)
    merged = []
    for group in by_key.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda t: (str(t.get("id", "")).startswith("youtube:"),
                                  str(t.get("id", ""))))
        dst = group[0]
        for src in group[1:]:
            if track_source_names(src) - track_source_names(dst):
                absorbed = merge_track_into(catalog, dst, src)
                merged.append({"into": dst["id"], "absorbed": absorbed,
                               "title": dst.get("title"),
                               "sources": sorted(track_source_names(dst))})
    return {"merged": len(merged), "pairs": merged}


def consolidate_catalog(catalog: dict, threshold: float = 0.86) -> dict:
    """Exact auto-merge everywhere + fuzzy near-matches for manual review.

    Returns {"merged": n, "pairs": [...], "needs_review": [...]}.
    Read-only except the exact merges it performs.
    """
    report: dict = {"merged": 0, "pairs": [], "needs_review": []}
    artist_ids = {a.get("id") for a in catalog.get("artists", [])}
    artist_ids |= {t.get("artist_id") for t in catalog.get("tracks", [])}
    for aid in sorted(artist_ids):
        summary = consolidate_artist(catalog, aid)
        report["merged"] += summary["merged"]
        report["pairs"].extend({**p, "artist_id": aid} for p in summary["pairs"])
    # fuzzy pass: same artist, disjoint-title tracks both lacking the
    # other's source, similar enough to deserve a human look
    names = {a.get("id"): a.get("name", a.get("id")) for a in catalog.get("artists", [])}
    by_artist: dict[str, list[dict]] = {}
    for t in catalog.get("tracks", []):
        by_artist.setdefault(t.get("artist_id"), []).append(t)
    for aid in sorted(by_artist):
        mine = by_artist[aid]
        for i in range(len(mine)):
            for j in range(i + 1, len(mine)):
                a, b = mine[i], mine[j]
                sa, sb = track_source_names(a), track_source_names(b)
                if sa == sb or not (sa ^ sb):
                    continue
                ratio = difflib.SequenceMatcher(
                    None,
                    normalize_track_title(a.get("title", "")),
                    normalize_track_title(b.get("title", ""))).ratio()
                if ratio >= threshold:
                    report["needs_review"].append({
                        "artist_id": aid, "artist": names.get(aid, aid),
                        "ratio": round(ratio, 3),
                        "a": {"id": a["id"], "title": a.get("title"),
                              "sources": sorted(sa)},
                        "b": {"id": b["id"], "title": b.get("title"),
                              "sources": sorted(sb)},
                    })
    report["needs_review"].sort(key=lambda e: (-e["ratio"], str(e["artist"])))
    return report


def coverage_report(catalog: dict) -> dict:
    """Per-track dual-source coverage: both / only-one-side / missing lists."""
    names = {a.get("id"): a.get("name", a.get("id")) for a in catalog.get("artists", [])}
    rep: dict = {"tracks": 0, "both": 0, "spotify_only": 0,
                 "youtube_only": 0, "other": 0,
                 "missing_spotify": [], "missing_youtube": []}
    for t in catalog.get("tracks", []):
        rep["tracks"] += 1
        s = track_source_names(t)
        entry = {"id": t.get("id"), "artist_id": t.get("artist_id"),
                 "artist": names.get(t.get("artist_id"), t.get("artist_id")),
                 "title": t.get("title"), "sources": sorted(s)}
        has_sp, has_yt = "spotify" in s, "youtube" in s
        if has_sp and has_yt:
            rep["both"] += 1
        elif has_sp:
            rep["spotify_only"] += 1
            rep["missing_youtube"].append(entry)
        elif has_yt:
            rep["youtube_only"] += 1
            rep["missing_spotify"].append(entry)
        else:
            rep["other"] += 1
            rep["missing_spotify"].append(entry)
            rep["missing_youtube"].append(entry)
    key = lambda e: (str(e["artist"]).casefold(), str(e["title"]).casefold())
    rep["missing_spotify"].sort(key=key)
    rep["missing_youtube"].sort(key=key)
    return rep
