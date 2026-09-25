"""Similarity-space visualization (SPEC #9): static HTML, no server.

Two views from the same vectors the candidate scorer uses
(``candidates.similarity``): a genre+artist map and a track map.
Positions come from a dependency-free 2D PCA over
[mean audio features, genre one-hots, log track-count / popularity];
when tracks carry no features the layout degrades to a deterministic
hash-jitter grid so the export never crashes on sparse catalogs.
Hover shows labels (SVG <title>), click fills an inspect panel
(inline vanilla JS, no CDN — offline-capable).
"""
from __future__ import annotations

import hashlib
import html
import math

from .candidates import _genres, _numbers, cosine_sim, jaccard


def artist_vector(catalog: dict, artist_id: str) -> dict:
    tracks = [t for t in catalog["tracks"] if t.get("artist_id") == artist_id]
    nums: dict[str, float] = {}
    if tracks:
        keys = {k for t in tracks for k in _numbers(t.get("features", {}))}
        for k in keys:
            vals = [_numbers(t.get("features", {})).get(k, 0.0) for t in tracks]
            nums[k] = sum(vals) / len(vals)
    genres: set[str] = set()
    for t in tracks:
        genres |= _genres(t)
    pops = [t.get("popularity", 0) or 0 for t in tracks]
    return {
        "features": nums,
        "genres": genres,
        "pop": sum(pops) / len(pops) if pops else 0.0,
        "count": len(tracks),
    }


def track_vector(track: dict) -> dict:
    return {
        "features": _numbers(track.get("features", {})),
        "genres": _genres(track),
        "pop": float(track.get("popularity", 0) or 0),
        "count": 1,
    }


def _combined_keys(vecs: list[dict]) -> tuple[list[str], list[str]]:
    fkeys = sorted({k for v in vecs for k in v["features"]})
    gkeys = sorted({g for v in vecs for g in v["genres"]})
    return fkeys, gkeys


def _to_rows(vecs: list[dict]) -> tuple[list[list[float]], list[str], list[str]]:
    fkeys, gkeys = _combined_keys(vecs)
    rows = []
    for v in vecs:
        row = [v["features"].get(k, 0.0) for k in fkeys]
        row += [1.0 if g in v["genres"] else 0.0 for g in gkeys]
        rows.append(row)
    return rows, fkeys, gkeys


def _pca_2d(rows: list[list[float]]) -> list[tuple[float, float]]:
    """Mean-centered PCA via power iteration + deflation. Deterministic."""
    n = len(rows)
    if n == 0:
        return []
    d = len(rows[0])
    if d == 0:
        return _fallback(n)
    means = [sum(r[j] for r in rows) / n for j in range(d)]
    centered = [[r[j] - means[j] for j in range(d)] for r in rows]
    if all(abs(v) < 1e-12 for r in centered for v in r):
        return _fallback(n)

    def power(mat: list[list[float]]) -> list[float]:
        v = [1.0 / math.sqrt(d)] * d
        for _ in range(100):
            w = [sum(mat[i][j] * v[j] for j in range(d)) for i in range(d)]
            # mat is symmetric covariance: w = C v
            norm = math.sqrt(sum(x * x for x in w))
            if norm < 1e-12:
                break
            w = [x / norm for x in w]
            if sum((w[i] - v[i]) ** 2 for i in range(d)) < 1e-10:
                v = w
                break
            v = w
        return v

    def cov(mat: list[list[float]]) -> list[list[float]]:
        n_ = len(mat)
        dd = len(mat[0])
        return [[sum(mat[i][a] * mat[i][b] for i in range(n_)) / max(n_, 1) for b in range(dd)] for a in range(dd)]

    pts: list[tuple[float, float]] = []
    residual = [r[:] for r in centered]
    comps = []
    for _ in range(2):
        c = cov(residual)
        v = power(c)
        comps.append(v)
        eig = sum(v[i] * sum(c[i][j] * v[j] for j in range(d)) for i in range(d))
        if eig < 1e-12:
            comps.append(v)
            break
        for r in residual:
            proj = sum(r[j] * v[j] for j in range(d))
            for j in range(d):
                r[j] -= proj * v[j]
    while len(comps) < 2:
        comps.append(comps[0])
    return [(sum(centered[i][j] * comps[0][j] for j in range(d)),
             sum(centered[i][j] * comps[1][j] for j in range(d))) for i in range(n)]


def _fallback(n: int) -> list[tuple[float, float]]:
    """Deterministic hash-jitter grid used when vectors carry no signal."""
    pts = []
    cols = max(1, math.isqrt(n))
    for i in range(n):
        h = int(hashlib.md5(f"viz-{i}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        pts.append((float(i % cols) + h * 0.8, float(i // cols) + (1 - h) * 0.8))
    return pts


def project(vecs: list[dict]) -> list[tuple[float, float]]:
    rows, _, _ = _to_rows(vecs)
    return _pca_2d(rows)


def _norm(pts: list[tuple[float, float]], w: float = 760.0, h: float = 460.0, pad: float = 30.0) -> list[tuple[float, float]]:
    if not pts:
        return pts
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    sx = (max(xs) - min(xs)) or 1.0
    sy = (max(ys) - min(ys)) or 1.0
    return [(pad + (x - min(xs)) / sx * (w - 2 * pad), pad + (y - min(ys)) / sy * (h - 2 * pad)) for x, y in pts]


def artist_distance(a: dict, b: dict) -> float:
    """0 (identical) .. ~1.3 (far): cosine gap on features + genre gap."""
    feat = 1.0 - cosine_sim(a["features"], b["features"])
    gen = 1.0 - jaccard(a["genres"], b["genres"])
    if not a["features"] and not b["features"] and not a["genres"] and not b["genres"]:
        return abs(a["pop"] - b["pop"]) / 100.0
    return 0.7 * feat + 0.3 * gen


def similar_artists(catalog: dict, artist_id: str, top: int = 5, least: bool = False) -> list[dict]:
    vecs = {a["id"]: artist_vector(catalog, a["id"]) for a in catalog["artists"]}
    if artist_id not in vecs:
        raise KeyError(f"unknown artist id: {artist_id}")
    base = vecs.pop(artist_id)
    rows = sorted(
        ({"id": aid, "distance": round(artist_distance(base, v), 4)} for aid, v in vecs.items()),
        key=lambda r: (r["distance"], r["id"]), reverse=least,
    )
    names = {a["id"]: a["name"] for a in catalog["artists"]}
    for r in rows:
        r["name"] = names.get(r["id"], r["id"])
    return rows[:top]


def similar_tracks(catalog: dict, track_id: str, top: int = 5, least: bool = False) -> list[dict]:
    from .candidates import similarity

    base = next((t for t in catalog["tracks"] if t.get("id") == track_id), None)
    if base is None:
        raise KeyError(f"unknown track id: {track_id}")
    rows = sorted(
        ({"id": t["id"], "title": t.get("title"), "distance": round(1.0 - similarity(t, base), 4)}
         for t in catalog["tracks"] if t.get("id") != track_id),
        key=lambda r: (r["distance"], r["id"] or ""), reverse=least,
    )
    return rows[:top]


def render_html(catalog: dict, title: str = "Music catalog similarity space") -> str:
    artists = catalog.get("artists", [])
    tracks = catalog.get("tracks", [])
    avecs = [artist_vector(catalog, a["id"]) for a in artists]
    tvecs = [track_vector(t) for t in tracks]
    apos = _norm(project(avecs))
    tpos = _norm(project(tvecs))
    track_counts = {a["id"]: avecs[i]["count"] for i, a in enumerate(artists)}

    def dots(items, pos, kind):
        out = []
        for (x, y), it in zip(pos, items):
            label = it.get("name") or it.get("title") or it.get("id")
            sub = f"{track_counts.get(it.get('id'), '')} tracks" if kind == "artist" else f"pop {it.get('popularity', 0)}"
            out.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" class="{kind}" '
                f'data-info="{html.escape(str(label))} — {html.escape(str(sub))}">'
                f"<title>{html.escape(str(label))} ({html.escape(str(sub))})</title></circle>"
            )
        return "\n".join(out)

    # genre nodes at member centroids
    genres: dict[str, list[int]] = {}
    for i, v in enumerate(avecs):
        for g in v["genres"]:
            genres.setdefault(g, []).append(i)
    gdots = []
    for g, idx in sorted(genres.items()):
        x = sum(apos[i][0] for i in idx) / len(idx)
        y = sum(apos[i][1] for i in idx) / len(idx)
        gdots.append(
            f'<rect x="{x - 7:.1f}" y="{y - 7:.1f}" width="14" height="14" class="genre" '
            f'data-info="genre: {html.escape(g)} ({len(idx)} artists)">'
            f"<title>genre: {html.escape(g)}</title></rect>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body{{font-family:sans-serif;max-width:900px;margin:2em auto;padding:0 1em}}
svg{{border:1px solid #ccc;width:100%;height:auto}}
circle.artist{{fill:#4a90d9}}circle.track{{fill:#7dbf45}}rect.genre{{fill:#e8a13c}}
#info{{border:1px solid #ccc;padding:.5em;min-height:2em;margin-top:.5em}}
</style></head><body>
<h1>{html.escape(title)}</h1>
<p>{len(artists)} artists, {len(tracks)} tracks. Hover for labels, click a point to inspect.</p>
<h2>Artists + genres</h2>
<svg viewBox="0 0 760 460" id="amap">{"".join(gdots)}
{dots(artists, apos, "artist")}</svg>
<h2>Tracks</h2>
<svg viewBox="0 0 760 460" id="tmap">{dots(tracks, tpos, "track")}</svg>
<div id="info">Click a point…</div>
<script>
document.querySelectorAll("circle,rect").forEach(function(el){{
  el.addEventListener("click",function(){{
    document.getElementById("info").textContent = el.getAttribute("data-info");
  }});
}});
</script>
</body></html>
"""
