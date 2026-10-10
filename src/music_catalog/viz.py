"""Similarity-space visualization (SPEC #9): static HTML, no server.

Two views from the same vectors the candidate scorer uses
(``candidates.similarity``): a genre+artist map and a track map.
Positions come from a dependency-free 2D PCA over
[mean audio features, genre one-hots, log track-count / popularity];
when tracks carry no features the layout degrades to a deterministic
hash-jitter grid so the export never crashes on sparse catalogs.
Hover shows labels (SVG <title>), click fills an inspect panel
(inline vanilla JS, no CDN — offline-capable).

``build_graph`` / ``render_site`` power the GitHub Pages browser
(``catalog viz --out-dir <data-repo>/docs``): a kNN similarity graph
(nodes = in-catalog artists, edges = trimmed similarity links)
rendered as a midnight-constellation canvas (force-graph 2D custom
paint: glow nodes, faint links, bubbles, tooltips) from ``graph.json``.
Page template lives in ``site_template.html`` beside this module.

The live site lives in the *data* repo (``docs/graph.json`` +
``docs/index.html``), generated natively from that repo's own
``state/catalog.json``. Every export stamps ``graph.meta`` with the
catalog fingerprint + timestamp, so ``catalog viz --check`` can tell
whether the published site went stale.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

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
    # artist-level tags (schema v2) join the same token space so tagged
    # artists cluster even when their tracks carry no genre metadata
    artist = next((a for a in catalog.get("artists", []) if a.get("id") == artist_id), None)
    if artist is not None:
        for g in list(artist.get("genres", [])) + list(artist.get("subgenres", [])):
            if str(g).strip():
                genres.add(str(g).strip().casefold())
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


def _spread(pts: list[tuple[float, float]], min_gap: float = 30.0) -> list[tuple[float, float]]:
    """Deterministic de-collision for stacked layout points.

    Points are placed in sorted order; each new point keeps its PCA
    position unless another placed point is closer than ``min_gap``,
    in which case it walks outward along a deterministic golden-angle
    spiral until clear. Same input → same output, so the stored
    layout stays stable across exports.
    """
    placed: list[tuple[float, float]] = []
    grid: dict[tuple[int, int], list[int]] = {}
    out: list[tuple[float, float] | None] = [None] * len(pts)

    def too_close(x: float, y: float) -> bool:
        cx, cy = math.floor(x / min_gap), math.floor(y / min_gap)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((cx + dx, cy + dy), ()):
                    px, py = placed[j]
                    if (px - x) ** 2 + (py - y) ** 2 < min_gap * min_gap:
                        return True
        return False

    for i in sorted(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1], i)):
        x, y = pts[i]
        h = int(hashlib.md5(f"spread-{i}".encode()).hexdigest()[:8], 16)
        ang = (h % 360) * math.pi / 180.0
        step = 0
        while too_close(x, y) and step < 500:
            step += 1
            ang += math.pi * (3.0 - math.sqrt(5.0))
            x = pts[i][0] + math.cos(ang) * min_gap * step * 0.5
            y = pts[i][1] + math.sin(ang) * min_gap * step * 0.5
        placed.append((x, y))
        out[i] = (x, y)
        grid.setdefault((math.floor(x / min_gap), math.floor(y / min_gap)), []).append(len(placed) - 1)
    return [p for p in out if p is not None]


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


GRAPH_K = 2  # nearest-neighbour distances pooled per artist (ties included)
MAX_DEGREE = 12  # hard cap on edges per node (hubs keep their closest links)
# Display trim budgets per edge level (see build_graph): how many of each
# kind a node keeps — closest wins. Union over both endpoints.
TRIM_BUDGETS = {0: 4, 1: 2, 2: 1}  # 0 intra-subgroup, 1 intra-group, 2 cross-group
FG_CDN = "https://cdn.jsdelivr.net/npm/force-graph@1.52.0/dist/force-graph.min.js"


def acronym_for(name: str) -> str:
    """2-letter acronym for the in-circle placeholder. Deterministic.

    First letters of first + last word (``DJ Snake`` -> ``DS``);
    single word uses its first two letters (``GIMS`` -> ``GI``).
    Diacritics stripped; empty names fall back to ``?``.
    """
    ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    words = [w for w in re.split(r"[^A-Za-z0-9]+", ascii_name) if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def catalog_fingerprint(catalog: dict) -> str:
    """Stable sha256 over the loaded catalog (canonical JSON, sorted keys).

    Same input dict → same fingerprint, so ``render_site`` can stamp an
    export and ``--check`` can later tell whether the catalog moved on.
    """
    canonical = json.dumps(catalog, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def cluster_for(genres) -> str:
    """One stable cluster id per artist: top-level taxonomy parent by vote.

    Track/artist genre tokens roll up through the taxonomy (aliases →
    canonical, subgenres → parent); tokens outside the taxonomy vote
    ``other``. Ties break alphabetically; genreless artists land in
    ``unknown``. Deterministic for a given token set.
    """
    from .tags import normalize_tag, parent_genre

    votes: dict[str, int] = {}
    for raw in genres or []:
        token = normalize_tag("genres", raw)
        if token is None:
            sub = normalize_tag("subgenres", raw)
            token = (parent_genre(sub) or "other") if sub is not None else "other"
        votes[token] = votes.get(token, 0) + 1
    if not votes:
        return "unknown"
    top = max(votes.values())
    return sorted(k for k, v in votes.items() if v == top)[0]


def genre_color(cid: str) -> str:
    """Node fill by cluster: taxonomy hue for genres, gray otherwise.

    Untagged / non-taxonomy clusters stay gray so genre color visibly
    lights up as tags are curated, without ever inventing signal.
    """
    from .tags import load_taxonomy

    if cid == "other" or cid.startswith("group-") or cid == "unknown":
        return "hsl(0, 0%, 74%)"
    genres = sorted(load_taxonomy()["genres"])
    if cid in genres:
        hue = round(genres.index(cid) * 360 / len(genres))
        return f"hsl({hue}, 55%, 70%)"
    return "hsl(0, 0%, 74%)"


def communities(ids: list[str], edges: list[dict], max_iter: int = 50) -> dict[str, str]:
    """Deterministic label-propagation communities over the capped graph.

    Gives the browser real bubbles before any genre tags exist
    (artists migrate to genre bubbles automatically once tagged).
    Async update in id order, smallest-label tiebreak, fixed cap —
    same graph + order → same communities.
    """
    from collections import Counter

    adj: dict[str, set[str]] = {aid: set() for aid in ids}
    for e in edges:
        adj[e["a"]].add(e["b"])
        adj[e["b"]].add(e["a"])
    label = {aid: aid for aid in ids}
    for _ in range(max_iter):
        changed = False
        for aid in ids:
            if not adj[aid]:
                continue
            freq = Counter(label[v] for v in adj[aid])
            top = max(freq.values())
            best = sorted(l for l, cnt in freq.items() if cnt == top)[0]
            if best != label[aid]:
                label[aid] = best
                changed = True
        if not changed:
            break
    return label


def build_graph(catalog: dict, k: int = GRAPH_K) -> dict:
    """kNN similarity graph over in-catalog artists (tracks >= 1).

    Nodes carry ``{id, name, acronym, color, tracks, pop, sources, x, y,
    cluster}``; ``x``/``y`` is a precomputed PCA layout (same projection
    as the static maps, de-collided) so the page renders instantly with
    every node frozen in place; ``cluster`` is the genre id where tags
    exist (see :func:`cluster_for`) else a ``group-*`` similarity
    community from deterministic label propagation — artists migrate
    to genre bubbles automatically once tagged. Node ``color`` follows
    the taxonomy hue for genres, gray while untagged.
    ``clusters`` lists ``{id, label, x, y, count}`` with the center
    precomputed as the member mean — the page collapses each cluster
    into one bubble and opens it on click, all from stored positions.
    Edges are undirected deduped ``{a, b, dist}`` pairs admitted
    closest-first with per-node degree capped at ``MAX_DEGREE``
    (sparse catalogs otherwise grow mega-hubs off distance ties).
    Candidate pools are tie-aware: every node tied at the k-th
    distance is admitted to the pool, so strict top-k truncation
    cannot starve nodes behind saturated hubs.
    Distances use the same vectors the CLI ``similar`` query uses, so
    page and CLI agree. Zero-track artists are excluded from the graph
    and reported as ``excluded_zero_track``.
    """
    artists = [a for a in catalog.get("artists", []) if a.get("status", "ok") == "ok"]
    vecs = {a["id"]: artist_vector(catalog, a["id"]) for a in artists}
    in_catalog = [a for a in artists if vecs[a["id"]]["count"] >= 1]
    # Precomputed layout: same PCA projection the static maps use, plus a
    # deterministic de-collision pass, so the browser renders instantly
    # with every node frozen in place. Positions are stable for a given
    # catalog.
    pos = _spread(_norm(project([vecs[a["id"]] for a in in_catalog]),
                        w=1600.0, h=1000.0, pad=60.0))
    nodes = []
    for i, ((x, y), a) in enumerate(zip(pos, in_catalog)):
        v = vecs[a["id"]]
        mine = [t for t in catalog.get("tracks", []) if t.get("artist_id") == a["id"]]
        sources = sorted({t.get("source", "?") for t in mine})
        nodes.append({
            "id": a["id"],
            "name": a.get("name", a["id"]),
            "acronym": acronym_for(a.get("name", "")),
            "color": "",  # filled below once the cluster is known
            "tracks": v["count"],
            "pop": round(v["pop"], 1),
            "sources": sources,
            "x": round(x, 1),
            "y": round(y, 1),
            "cluster": "",
        })
    ids = [a["id"] for a in in_catalog]
    ranked: dict[str, list[tuple[float, str]]] = {}
    for aid in ids:
        dists = sorted(
            ((artist_distance(vecs[aid], vecs[other]), other) for other in ids if other != aid)
        )
        # Tie-aware pool: every node tied at the k-th distance joins the
        # candidate pool ("k nearest distances", not "k nearest nodes").
        # Sparse catalogs tie en masse; a strict top-k would point every
        # node at the same few lowest-id hubs and starve the rest.
        thresh = dists[min(k, len(dists)) - 1][0] if dists else 0.0
        ranked[aid] = [(d, o) for d, o in dists if d <= thresh + 1e-12]
    # Fair round-robin admission: each node takes its closest still-open
    # link in turn (deterministic id order). Closest-first per node, but
    # no node is starved by hubs filling up early, and no node exceeds
    # MAX_DEGREE (over-subscribed hubs keep their closest links).
    deg: dict[str, int] = {aid: 0 for aid in ids}
    admitted: set[tuple[str, str]] = set()
    edges = []
    progress = True
    while progress:
        progress = False
        for u in ids:
            if deg[u] >= MAX_DEGREE:
                continue
            for dist, v in ranked[u]:
                key = (min(u, v), max(u, v))
                if key in admitted:
                    continue
                if deg[v] >= MAX_DEGREE:
                    continue
                admitted.add(key)
                deg[u] += 1
                deg[v] += 1
                edges.append({"a": key[0], "b": key[1], "dist": round(dist, 4)})
                progress = True
                break
    # Hybrid clusters: genre vote where tags exist, else a two-level
    # similarity hierarchy — LP communities (top), then LP per community
    # on its induced subgraph, then a deterministic median-cut so every
    # leaf bubble holds <= 40 artists. Artists migrate to genre bubbles
    # automatically once tagged; untagged artists bubble by similarity now.
    comm = communities(ids, edges)
    xy = {n["id"]: (n["x"], n["y"]) for n in nodes}
    top_of: dict[str, str] = {}
    for n in nodes:
        tokens = vecs[n["id"]]["genres"]
        top_of[n["id"]] = cluster_for(tokens) if tokens else f"group-{comm[n['id']]}"

    def _split_big(items: list[tuple], max_size: int = 40, depth: int = 0) -> list[list[tuple]]:
        # items: [(aid, x, y)] -> balanced median-cut leaves. Splits along
        # the wider axis at the median (id breaks ties); deterministic.
        if len(items) <= max_size or depth >= 4:
            return [items]
        xs = [p[1] for p in items]
        ys = [p[2] for p in items]
        axis = 1 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 2
        ordered = sorted(items, key=lambda p: (p[axis], p[0]))
        mid = len(ordered) // 2
        return _split_big(ordered[:mid], max_size, depth + 1) + _split_big(ordered[mid:], max_size, depth + 1)

    leaf_of: dict[str, str] = {}  # aid -> finest cluster id
    leaf_parent: dict[str, str | None] = {}  # finest -> top (None == top itself)
    for top in sorted(set(top_of.values())):
        members = sorted(aid for aid in ids if top_of[aid] == top)
        if top.startswith("group-"):
            mset = set(members)
            induced = [e for e in edges if e["a"] in mset and e["b"] in mset]
            sublabels = communities(members, induced)
            buckets: dict[str, list[str]] = {}
            for aid in members:
                buckets.setdefault(sublabels[aid], []).append(aid)
            parts = []
            for sub in sorted(buckets):
                parts.extend(_split_big([(aid,) + xy[aid] for aid in sorted(buckets[sub])]))
        else:
            parts = _split_big([(aid,) + xy[aid] for aid in members])
        if len(parts) == 1:
            for aid in members:
                leaf_of[aid] = top
            leaf_parent[top] = None
        else:
            # letter leaves westernmost -> easternmost for spatial stability
            ordered = sorted(parts, key=lambda p: (sum(xy[aid][0] for aid, _, _ in p) / len(p),
                                                   sum(xy[aid][1] for aid, _, _ in p) / len(p),
                                                   p[0][0]))
            for k, part in enumerate(ordered):
                finest = f"{top}/{chr(ord('a') + k) if k < 26 else f'x{k}'}"
                for aid, _, _ in part:
                    leaf_of[aid] = finest
                leaf_parent[finest] = top
    by_cluster: dict[str, list[int]] = {}
    for i, n in enumerate(nodes):
        n["cluster"] = leaf_of[n["id"]]
        n["top"] = top_of[n["id"]]
        n["color"] = genre_color(n["cluster"])
        by_cluster.setdefault(n["cluster"], []).append(i)
    # Display trim: classify each edge by the level at which its endpoints
    # diverge (0 same subgroup, 1 same top group, 2 cross-group) and keep,
    # per node and level, only the closest TRIM_BUDGETS[lvl] (union over
    # both endpoints, so a node never loses its own closest link of any
    # kind — trimming cannot isolate). Similarity queries use vectors,
    # not edges, so nothing analytical is lost: edges are a display subset.
    by_id = {n["id"]: n for n in nodes}
    for e in edges:
        a, b = by_id[e["a"]], by_id[e["b"]]
        e["lvl"] = 0 if a["cluster"] == b["cluster"] else (1 if a["top"] == b["top"] else 2)
    per_node: dict[str, dict[int, list[int]]] = {}
    for i, e in enumerate(edges):
        for u in (e["a"], e["b"]):
            per_node.setdefault(u, {}).setdefault(e["lvl"], []).append(i)
    keep: set[int] = set()
    for u, lvls in per_node.items():
        for lvl, idxs in lvls.items():
            idxs.sort(key=lambda i: (edges[i]["dist"], edges[i]["a"], edges[i]["b"]))
            keep.update(idxs[:TRIM_BUDGETS[lvl]])
    edges = [e for i, e in enumerate(edges) if i in keep]
    # Local weight: how the edge ranks among each endpoint's *kept* edges.
    # w=1 when it is both endpoints' closest — the links that matter there.
    indeg: dict[str, list[int]] = {}
    for i, e in enumerate(edges):
        indeg.setdefault(e["a"], []).append(i)
        indeg.setdefault(e["b"], []).append(i)
    for idxs in indeg.values():
        idxs.sort(key=lambda i: (edges[i]["dist"], edges[i]["a"], edges[i]["b"]))
    for u, idxs in indeg.items():
        for rank, i in enumerate(idxs):
            edges[i][f"rank_{u}"] = rank
    for e in edges:
        da, db = len(indeg[e["a"]]), len(indeg[e["b"]])
        e["w"] = round(1.0 - (e.pop(f"rank_{e['a']}") / da + e.pop(f"rank_{e['b']}") / db) / 2.0, 3)
    tops = sorted({leaf_parent[c] or c for c in by_cluster},
                    key=lambda t: (-sum(len(by_cluster[x]) for x in by_cluster
                                        if x == t or leaf_parent.get(x) == t), t))
    group_rank = {t: i + 1 for i, t in enumerate(tops) if t.startswith("group-")}
    children: dict[str, list[str]] = {}
    for cid in by_cluster:
        p = leaf_parent[cid]
        if p is not None:
            children.setdefault(p, []).append(cid)
    # entries: every leaf + every split top (so split tops bubble too)
    entries = [(cid, leaf_parent[cid]) for cid in by_cluster]
    entries += [(t, None) for t in children]
    clusters = []
    for cid, parent in sorted(entries):
        if parent is None and cid in children:
            idx = [i for sub in children[cid] for i in by_cluster[sub]]
        else:
            idx = by_cluster[cid]
        if parent is None:
            label = f"Group {group_rank[cid]}" if cid in group_rank else cid
        else:
            suffix = cid.rsplit("/", 1)[1]
            label = (f"Group {group_rank[parent]}{suffix}" if parent in group_rank
                     else f"{parent} {suffix}")
        clusters.append({
            "id": cid,
            "label": label,
            "parent": parent,
            "x": round(sum(nodes[i]["x"] for i in idx) / len(idx), 1),
            "y": round(sum(nodes[i]["y"] for i in idx) / len(idx), 1),
            "count": len(idx),
        })
    zero = sum(1 for a in artists if vecs[a["id"]]["count"] == 0)
    return {"nodes": nodes, "edges": edges, "excluded_zero_track": zero,
            "clusters": clusters}


def _site_template() -> str:
    """Load the browser page template (lives beside this module)."""
    return (Path(__file__).with_name("site_template.html")).read_text(encoding="utf-8")


SITE_TEMPLATE = _site_template()


def render_site(catalog: dict, out_dir: str | Path,
                title: str = "Music catalog — artist constellation",
                catalog_sha: str | None = None) -> dict:
    """Export the GitHub Pages site: ``graph.json`` + ``index.html``.

    The export is stamped with ``meta`` (catalog fingerprint +
    generation time) so staleness is checkable without rebuilding.
    Returns ``{"dir": ..., "nodes": ..., "edges": ..., "excluded_zero_track": ...,
    "catalog_sha256": ..., "generated_at": ...}``.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    graph = build_graph(catalog)
    sha = catalog_sha or catalog_fingerprint(catalog)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    graph["meta"] = {"catalog_sha256": sha, "generated_at": generated_at,
                     "generator": "music-catalog-viz"}
    with open(out / "graph.json", "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)
    page = SITE_TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__FG_CDN__", FG_CDN)
    with open(out / "index.html", "w", encoding="utf-8") as f:
        f.write(page)
    return {"dir": str(out), "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "excluded_zero_track": graph["excluded_zero_track"],
            "catalog_sha256": sha, "generated_at": generated_at}

