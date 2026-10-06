"""Artist/track tags: genres, subgenres, instruments (phase A, manual curation).

Controlled vocabulary lives in ``taxonomy.json`` (versioned, code repo):
``genres`` (top level), ``subgenres`` (each mapped to exactly one parent
genre), ``instruments``, plus an ``aliases`` map for raw API/folksonomy
strings to canonical form. Unknown tags are rejected (``ValueError``) so
they surface in ``catalog tags review`` instead of polluting the catalog —
the same "never silently merged" rule as unknown artists.

Storage (schema v2, additive): artists carry ``genres`` / ``subgenres`` /
``instruments`` lists plus ``tag_source`` (``manual`` | enrichment name)
and ``tagged_at``; tracks may carry ``genres`` / ``instruments`` as an
override (non-empty track list wins, else the artist's). Instruments are
display/filter metadata in v1 and do not enter similarity scoring.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

TAG_FIELDS = ("genres", "subgenres", "instruments")

_taxonomy: dict | None = None


def load_taxonomy() -> dict:
    """Load (and cache) the controlled vocabulary."""
    global _taxonomy
    if _taxonomy is None:
        path = Path(__file__).with_name("taxonomy.json")
        with open(path, encoding="utf-8") as f:
            _taxonomy = json.load(f)
    return _taxonomy


def _canon_key(raw: str) -> str:
    import re

    return re.sub(r"[\s_]+", "-", (raw or "").strip().casefold())


def normalize_tag(kind: str, raw: str) -> str | None:
    """Map a raw tag to canonical form, or ``None`` if outside the taxonomy."""
    tax = load_taxonomy()
    if kind == "subgenres":
        vocab = {s for subs in tax["subgenres"].values() for s in subs}
    elif kind in ("genres", "instruments"):
        vocab = set(tax[kind])
    else:
        raise ValueError(f"unknown tag kind: {kind}")
    key = _canon_key(raw)
    key = tax.get("aliases", {}).get(key, key)
    return key if key in vocab else None


def parent_genre(subgenre: str) -> str | None:
    """Parent genre for a canonical subgenre, or ``None``."""
    for parent, subs in load_taxonomy()["subgenres"].items():
        if subgenre in subs:
            return parent
    return None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def blank_tags() -> dict:
    return {"genres": [], "subgenres": [], "instruments": [],
            "tag_source": None, "tagged_at": None}


def migrate_catalog(catalog: dict) -> int:
    """Add missing tag fields to artists/tracks (schema v1 -> v2). Idempotent.

    Returns the number of records touched.
    """
    touched = 0
    for a in catalog.get("artists", []):
        blank = blank_tags()
        for k, v in blank.items():
            if k not in a:
                a[k] = v
                touched += 1
    for t in catalog.get("tracks", []):
        for k in ("genres", "instruments"):
            if k not in t:
                t[k] = []
                touched += 1
    if catalog.get("version", 1) < 2:
        catalog["version"] = 2
    return touched


def set_artist_tags(catalog: dict, artist_id: str, genres: list[str] | None = None,
                    subgenres: list[str] | None = None,
                    instruments: list[str] | None = None,
                    source: str = "manual", clear: bool = False) -> dict:
    """Replace (or clear) an artist's tags. Validates against the taxonomy.

    Setting a subgenre auto-adds its parent genre. Raises ``KeyError`` for
    unknown artists, ``ValueError`` listing rejected tags.
    """
    artist = next((a for a in catalog["artists"] if a.get("id") == artist_id), None)
    if artist is None:
        raise KeyError(f"unknown artist id: {artist_id}")
    if clear:
        genres, subgenres, instruments = [], [], []
    bad: dict[str, list[str]] = {}
    canon: dict[str, list[str]] = {}
    for kind, vals in (("genres", genres or []), ("subgenres", subgenres or []),
                       ("instruments", instruments or [])):
        good, rejected = [], []
        for raw in vals:
            c = normalize_tag(kind, raw)
            if c is None:
                rejected.append(raw)
            elif c not in good:
                good.append(c)
        canon[kind] = good
        if rejected:
            bad[kind] = rejected
    if bad:
        raise ValueError(f"tags outside taxonomy: {bad}")
    final_genres = list(canon["genres"])
    for sub in canon["subgenres"]:
        parent = parent_genre(sub)
        if parent is not None and parent not in final_genres:
            final_genres.append(parent)
    artist["genres"] = sorted(final_genres)
    artist["subgenres"] = sorted(canon["subgenres"])
    artist["instruments"] = sorted(canon["instruments"])
    artist["tag_source"] = source
    artist["tagged_at"] = _now()
    return {"id": artist_id, "genres": artist["genres"],
            "subgenres": artist["subgenres"], "instruments": artist["instruments"],
            "source": source}


def find_artist_tags(catalog: dict, artist_id: str) -> dict:
    artist = next((a for a in catalog["artists"] if a.get("id") == artist_id), None)
    if artist is None:
        raise KeyError(f"unknown artist id: {artist_id}")
    return {"id": artist_id, "name": artist.get("name"),
            "genres": artist.get("genres", []), "subgenres": artist.get("subgenres", []),
            "instruments": artist.get("instruments", []),
            "tag_source": artist.get("tag_source"), "tagged_at": artist.get("tagged_at")}


def effective_genres(catalog: dict, track: dict) -> list[str]:
    """Track override if non-empty, else the artist's genres+subgenres."""
    if track.get("genres"):
        return sorted({str(g).casefold() for g in track["genres"]})
    artist = next((a for a in catalog["artists"]
                   if a.get("id") == track.get("artist_id")), None)
    if artist is None:
        return []
    return sorted({str(g).casefold() for g in artist.get("genres", [])}
                  | {str(g).casefold() for g in artist.get("subgenres", [])})


def effective_instruments(catalog: dict, track: dict) -> list[str]:
    """Track override if non-empty, else the artist's instruments."""
    if track.get("instruments"):
        return sorted({str(i).casefold() for i in track["instruments"]})
    artist = next((a for a in catalog["artists"]
                   if a.get("id") == track.get("artist_id")), None)
    if artist is None:
        return []
    return sorted({str(i).casefold() for i in artist.get("instruments", [])})


def untagged_artists(catalog: dict) -> list[dict]:
    """In-catalog artists with no genre/subgenre tags (curation queue)."""
    out = []
    for a in catalog.get("artists", []):
        if not a.get("genres") and not a.get("subgenres"):
            n = sum(1 for t in catalog.get("tracks", []) if t.get("artist_id") == a.get("id"))
            if n >= 1:
                out.append({"id": a["id"], "name": a.get("name"),
                            "tracks": n, "tag_source": a.get("tag_source")})
    out.sort(key=lambda e: e["name"].casefold())
    return out


def coverage(catalog: dict) -> dict:
    """Tag coverage stats by source."""
    by_source: dict[str, int] = {}
    tagged = 0
    in_catalog = 0
    for a in catalog.get("artists", []):
        n = sum(1 for t in catalog.get("tracks", []) if t.get("artist_id") == a.get("id"))
        if n == 0:
            continue
        in_catalog += 1
        if a.get("genres") or a.get("subgenres"):
            tagged += 1
            by_source[a.get("tag_source") or "unknown"] = by_source.get(a.get("tag_source") or "unknown", 0) + 1
    return {"in_catalog_artists": in_catalog, "tagged": tagged,
            "untagged": in_catalog - tagged, "by_source": by_source}


def validate_catalog(catalog: dict) -> list[dict]:
    """Records carrying tags outside the taxonomy (should be empty)."""
    tax = load_taxonomy()
    vocab_g, vocab_i = set(tax["genres"]), set(tax["instruments"])
    vocab_s = {s for subs in tax["subgenres"].values() for s in subs}
    bad = []
    for a in catalog.get("artists", []):
        entry = {"id": a.get("id"), "name": a.get("name"), "bad": {}}
        for kind, vocab in (("genres", vocab_g), ("subgenres", vocab_s),
                            ("instruments", vocab_i)):
            unknown = [t for t in a.get(kind, []) if _canon_key(t) not in vocab]
            if unknown:
                entry["bad"][kind] = unknown
        if entry["bad"]:
            bad.append(entry)
    return bad
