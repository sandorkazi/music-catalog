"""Candidate scorer (SPEC #8): popular-but-dissimilar picks for gap artists.

For an artist with < 2 tracks, rank a pool of candidate tracks by
``popularity − similarity`` and pick 2: highest popularity wins, but
near-duplicates of tracks the artist already has are pushed down.
Similarity blends audio-feature cosine distance with genre-tag Jaccard
distance; when tracks carry no features (e.g. bare YouTube rows with
``features: {}``) similarity is 0 and popularity alone decides, with
title-token overlap as a last-resort dissimilarity tie-break.
"""
from __future__ import annotations

import math

FEATURE_WEIGHT = 0.7
GENRE_WEIGHT = 0.3


def _numbers(features: dict) -> dict[str, float]:
    out = {}
    for k, v in (features or {}).items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and math.isfinite(v):
            out[k] = float(v)
    return out


def _genres(track: dict) -> set[str]:
    g = track.get("genres") or track.get("features", {}).get("genre") or []
    if isinstance(g, str):
        g = [g]
    return {str(x).strip().casefold() for x in g if str(x).strip()}


def cosine_sim(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def title_overlap(a: str, b: str) -> float:
    ta = {w for w in (a or "").casefold().split() if len(w) > 2}
    tb = {w for w in (b or "").casefold().split() if len(w) > 2}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def similarity(candidate: dict, existing: dict) -> float:
    """0 (dissimilar) .. 1 (near-duplicate)."""
    feat = cosine_sim(_numbers(candidate.get("features", {})), _numbers(existing.get("features", {})))
    gen = jaccard(_genres(candidate), _genres(existing))
    if feat == 0.0 and gen == 0.0:
        # no signal: fall back to title overlap so remixes/live dupes sink
        return title_overlap(candidate.get("title", ""), existing.get("title", ""))
    return FEATURE_WEIGHT * feat + GENRE_WEIGHT * gen


def score_candidate(candidate: dict, existing_tracks: list[dict], pop_max: float) -> dict:
    """Score one candidate. Higher is better: popular, far from owned tracks."""
    pop = candidate.get("popularity", 0) or 0
    pop_norm = (pop / pop_max) if pop_max > 0 else 0.0
    sim = 0.0
    for owned in existing_tracks:
        if owned.get("id") == candidate.get("id"):
            continue
        sim = max(sim, similarity(candidate, owned))
    return {
        "id": candidate.get("id"),
        "title": candidate.get("title"),
        "popularity": pop,
        "similarity": round(sim, 4),
        "score": round(pop_norm - sim, 4),
    }


def pick_candidates(existing_tracks: list[dict], pool: list[dict], k: int = 2) -> dict:
    """Rank ``pool`` against ``existing_tracks``; return ranked list + top-k pick."""
    owned_ids = {t.get("id") for t in existing_tracks}
    fresh = [c for c in pool if c.get("id") not in owned_ids]
    pop_max = max([c.get("popularity", 0) or 0 for c in fresh], default=0)
    ranked = sorted(
        (score_candidate(c, existing_tracks, pop_max) for c in fresh),
        key=lambda r: (-r["score"], -(r["popularity"] or 0), r["id"] or ""),
    )
    return {"ranked": ranked, "picked": [r["id"] for r in ranked[:k]]}
