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
(nodes = in-catalog artists with acronym-in-circle placeholders,
edges = top-k nearest neighbours) rendered with vis-network
(force layout, zoom, hover info panel, filters) from ``graph.json``.

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


GRAPH_K = 3  # edges per artist (nearest neighbours)
MAX_DEGREE = 20  # hard cap on edges per node (hubs keep their closest links)
VIS_CDN = "https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"


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


def color_for(artist_id: str) -> str:
    """Deterministic pastel fill color derived from the artist id."""
    h = int(hashlib.md5(f"node-{artist_id}".encode()).hexdigest()[:8], 16)
    return f"hsl({h % 360}, 55%, 72%)"


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


def build_graph(catalog: dict, k: int = GRAPH_K) -> dict:
    """kNN similarity graph over in-catalog artists (tracks >= 1).

    Nodes carry ``{id, name, acronym, color, tracks, pop, sources, x, y,
    cluster}``; ``x``/``y`` is a precomputed PCA layout (same projection
    as the static maps) so the page renders instantly with physics off;
    ``cluster`` is the genre-cluster id (see :func:`cluster_for`).
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
    # Precomputed layout: same PCA projection the static maps use, so the
    # browser renders instantly instead of running force physics on load.
    # Positions are deterministic for a given catalog.
    pos = _norm(project([vecs[a["id"]] for a in in_catalog]),
                w=1600.0, h=1000.0, pad=60.0)
    nodes = []
    for i, ((x, y), a) in enumerate(zip(pos, in_catalog)):
        v = vecs[a["id"]]
        mine = [t for t in catalog.get("tracks", []) if t.get("artist_id") == a["id"]]
        sources = sorted({t.get("source", "?") for t in mine})
        nodes.append({
            "id": a["id"],
            "name": a.get("name", a["id"]),
            "acronym": acronym_for(a.get("name", "")),
            "color": color_for(a["id"]),
            "tracks": v["count"],
            "pop": round(v["pop"], 1),
            "sources": sources,
            "x": round(x, 1),
            "y": round(y, 1),
            "cluster": cluster_for(v["genres"]),
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
    # MAX_DEGREE (over-subscribed hubs keep their 20 closest links).
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
    by_cluster: dict[str, list[int]] = {}
    for i, n in enumerate(nodes):
        by_cluster.setdefault(n["cluster"], []).append(i)
    clusters = []
    for cid in sorted(by_cluster):
        idx = by_cluster[cid]
        clusters.append({
            "id": cid,
            "label": cid,
            "x": round(sum(nodes[i]["x"] for i in idx) / len(idx), 1),
            "y": round(sum(nodes[i]["y"] for i in idx) / len(idx), 1),
            "count": len(idx),
        })
    zero = sum(1 for a in artists if vecs[a["id"]]["count"] == 0)
    return {"nodes": nodes, "edges": edges, "excluded_zero_track": zero,
            "clusters": clusters}


SITE_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
body{font-family:sans-serif;margin:0;padding:0 1em;max-width:1200px;margin-inline:auto}
#toolbar{display:flex;flex-wrap:wrap;gap:.75em;align-items:center;margin:.75em 0}
#toolbar label{font-size:.85em}
#layout{display:grid;grid-template-columns:1fr 280px;gap:1em}
#network{border:1px solid #ccc;height:70vh;min-height:420px}
#info{border:1px solid #ccc;padding:.75em;font-size:.9em;max-height:70vh;overflow:auto}
#info h2{margin:.2em 0;font-size:1.1em}
#info ul{padding-left:1.2em;margin:.4em 0}
footer{color:#666;font-size:.8em;margin:1em 0 2em}
@media(max-width:800px){#layout{grid-template-columns:1fr}}
</style></head><body>
<h1>__TITLE__</h1>
<p id="counts">Loading…</p>
<div id="toolbar">
<label>Search <input id="q" type="search" placeholder="artist name"></label>
<label>Source <select id="f-source"><option value="">all</option></select></label>
<label>Min tracks <select id="f-tracks"><option value="1">1+</option><option value="2">2+</option><option value="3">3+</option></select></label>
<label>Min popularity <input id="f-pop" type="range" min="0" max="100" value="0"> <span id="f-pop-v">0</span></label>
<label><input id="f-edges" type="checkbox" checked> edges</label>
<label title="Re-run the force layout in your browser (slow on large graphs)"><input id="f-phys" type="checkbox"> physics</label>
<button id="f-expand" title="Open every genre bubble">Expand all</button>
<button id="f-collapse" title="Collapse back to genre bubbles">Collapse all</button>
<button id="f-reset">Reset</button>
</div>
<div id="layout">
<div id="network" role="application" aria-label="Artist similarity graph. Scroll to zoom, drag to pan."></div>
<aside id="info"><h2>Artist info</h2><p>Artists start grouped in genre bubbles — click a bubble to open it. Hover a circle to preview, click to pin. Scroll to zoom, drag to pan. Layout is precomputed; tick physics to re-spread.</p></aside>
</div>
<footer>Metadata (names, counts) from the curated catalog in this repo (<code>state/catalog.json</code>). No audio, lyrics, or artwork hosted here. Mistake? File a takedown via the repo issues page.<br>Generated from the dataset in this repo — regenerate with <code>catalog viz --out-dir docs</code> whenever the catalog changes. Local preview needs http (`python3 -m http.server`) — opening via file:// blocks graph.json.</footer>
<script src="__VIS_CDN__"></script>
<script>
var ALL = null, network = null, nodes = null, edges = null, pinned = null;
function infoHTML(n){
  var sims = ALL.edges.filter(function(e){return e.a===n.id||e.b===n.id;})
    .map(function(e){var o=e.a===n.id?e.b:e.a;var m=ALL.byId[o];return {n:m,d:e.dist};})
    .sort(function(x,y){return x.d-y.d;}).slice(0,5);
  var h = "<h2>"+escapeHTML(n.name)+"</h2><p>"+n.tracks+" track(s) · pop "+n.pop+" · "+n.sources.join(", ")+"</p>";
  h += "<p><strong>Nearest neighbours</strong></p><ul>"+sims.map(function(s){
    return "<li><a href='#' data-id='"+s.n.id+"'>"+escapeHTML(s.n.name)+"</a> ("+s.d.toFixed(2)+")</li>";}).join("")+"</ul>";
  return h;
}
function escapeHTML(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];});}
function passFilters(n){
  var src = document.getElementById("f-source").value;
  var mt = parseInt(document.getElementById("f-tracks").value,10);
  var mp = parseInt(document.getElementById("f-pop").value,10);
  var q = document.getElementById("q").value.trim().toLowerCase();
  if(src && n.sources.indexOf(src)<0) return false;
  if(n.tracks<mt||n.pop<mp) return false;
  if(q && n.name.toLowerCase().indexOf(q)<0) return false;
  return true;
}
function applyFilters(){
  var filtering = document.getElementById("q").value.trim() !== "" ||
    document.getElementById("f-source").value !== "" ||
    document.getElementById("f-tracks").value !== "1" ||
    document.getElementById("f-pop").value !== "0";
  if(filtering) expandAll();
  var vis = ALL.nodes.filter(passFilters).map(function(n){return n.id;});
  var visSet = {}; vis.forEach(function(id){visSet[id]=true;});
  nodes.get().forEach(function(n){nodes.update({id:n.id,hidden:!visSet[n.id]});});
  var showE = document.getElementById("f-edges").checked;
  edges.get().forEach(function(e){
    var edge = ALL.edges.filter(function(x){return x.id===e.id;})[0];
    edges.update({id:e.id,hidden:!showE||!visSet[edge.a]||!visSet[edge.b]});
  });
}
function highlight(id){
  var connected = {}; connected[id]=true;
  network.getConnectedNodes(id).forEach(function(x){connected[x]=true;});
  nodes.get().forEach(function(n){
    nodes.update({id:n.id,opacity:connected[n.id]?1:0.15});
  });
  edges.get().forEach(function(e){
    var edge = ALL.edges.filter(function(x){return x.id===e.id;})[0];
    edges.update({id:e.id,color:{opacity:(edge.a===id||edge.b===id)?1:0.08}});
  });
}
function clearHighlight(){
  nodes.get().forEach(function(n){nodes.update({id:n.id,opacity:1});});
  edges.get().forEach(function(e){edges.update({id:e.id,color:{opacity:1}});});
}
function showInfo(id){
  if(String(id).indexOf("cluster:")===0){
    var c = (ALL.clusters||[]).filter(function(x){return "cluster:"+x.id===id;})[0];
    document.getElementById("info").innerHTML =
      "<h2>"+escapeHTML(c.label)+"</h2><p>"+c.count+" artist(s) · click the bubble to open it</p>";
    return;
  }
  document.getElementById("info").innerHTML = infoHTML(ALL.byId[id]);
}
function clusterColor(id){var h=0;var s="cluster-"+id;for(var i=0;i<s.length;i++){h=(h*31+s.charCodeAt(i))>>>0;}return "hsl("+(h%360)+", 60%, 70%)";}
function openClusters(){return (ALL.clusters||[]).map(function(c){return "cluster:"+c.id;}).filter(function(cid){return network.findNode(cid).length>0;});}
function expandAll(){openClusters().forEach(function(cid){network.openCluster(cid);});}
function collapseAll(){
  (ALL.clusters||[]).forEach(function(c){
    if(c.id==="unknown") return; // no genre signal: members stay flat
    if(c.count<2||network.findNode("cluster:"+c.id).length>0) return;
    network.cluster({
      joinCondition:function(n){return n.cl===c.id;},
      clusterNodeProperties:{id:"cluster:"+c.id,label:c.label+" ("+c.count+")",shape:"dot",
        size:16+Math.min(34,c.count),x:c.x,y:c.y,
        color:{background:clusterColor(c.id),border:"#333"},
        font:{size:16,face:"sans-serif",bold:true}}
    });
  });
}
fetch("graph.json").then(function(r){if(!r.ok)throw new Error(r.status);return r.json();}).then(function(g){
  ALL = g; ALL.byId = {};
  g.nodes.forEach(function(n){ALL.byId[n.id]=n;});
  var srcs = {}; g.nodes.forEach(function(n){n.sources.forEach(function(s){srcs[s]=true;});});
  Object.keys(srcs).sort().forEach(function(s){
    var o=document.createElement("option");o.value=s;o.textContent=s;
    document.getElementById("f-source").appendChild(o);
  });
  document.getElementById("counts").textContent =
    g.nodes.length+" artists in "+(g.clusters||[]).length+" genre clusters, "+g.edges.length+" similarity links ("+g.excluded_zero_track+" zero-track artists excluded). "+freshnessLine(g.meta||{});
function freshnessLine(meta){
  var bits = [];
  if(meta.generated_at) bits.push("updated "+meta.generated_at);
  if(meta.catalog_sha256) bits.push("catalog "+String(meta.catalog_sha256).slice(0,8));
  return bits.length ? "("+bits.join(" · ")+")" : "(no freshness stamp — regenerate the export)";
}
  var vNodes = g.nodes.map(function(n,i){
    return {id:n.id,label:n.acronym,title:escapeHTML(n.name)+" — "+n.tracks+" tracks",
      shape:"circle",color:{background:n.color,border:"#555"},value:10+n.tracks*8,
      x:n.x,y:n.y,cl:n.cluster,font:{size:14,face:"sans-serif"}};
  });
  var vEdges = g.edges.map(function(e,i){
    return {id:"e"+i,from:e.a,to:e.b,value:Math.max(0.2,1.2-e.dist),
      color:{opacity:1},smooth:false};
  });
  g.edges.forEach(function(e,i){e.id="e"+i;});
  nodes = new vis.DataSet(vNodes); edges = new vis.DataSet(vEdges);
  network = new vis.Network(document.getElementById("network"),{nodes:nodes,edges:edges},{
    physics:{enabled:false,solver:"barnesHut",barnesHut:{gravitationalConstant:-4000,springLength:120,avoidOverlap:0.3},stabilization:{enabled:true,iterations:150}},
    interaction:{hover:true,hoverConnectedEdges:false,zoomView:true,dragView:true,multiselect:false,hideEdgesOnDrag:true},
    nodes:{borderWidth:1},edges:{smooth:false}
  });
  document.getElementById("f-phys").addEventListener("change",function(ev){
    network.setOptions({physics:{enabled:ev.target.checked}});
  });
  network.on("hoverNode",function(p){showInfo(p.node);highlight(p.node);network.focus(p.node,{scale:1.6,animation:{duration:400}});});
  network.on("blurNode",function(){if(!pinned)clearHighlight();});
  network.on("click",function(p){
    if(p.nodes.length){
      var cid = String(p.nodes[0]);
      if(cid.indexOf("cluster:")===0){showInfo(cid);network.openCluster(cid);return;}
      pinned=p.nodes[0];showInfo(pinned);highlight(pinned);
    }
    else{pinned=null;clearHighlight();}
  });
  document.getElementById("info").addEventListener("click",function(ev){
    var a = ev.target.closest ? ev.target.closest("a[data-id]") : null;
    if(a){ev.preventDefault();var id=a.getAttribute("data-id");pinned=id;showInfo(id);highlight(id);network.focus(id,{scale:1.6,animation:{duration:400}});network.selectNodes([id]);}
  });
  ["q","f-source","f-tracks","f-pop","f-edges"].forEach(function(id){
    document.getElementById(id).addEventListener("input",function(){
      document.getElementById("f-pop-v").textContent=document.getElementById("f-pop").value;
      applyFilters();
    });
  });
  document.getElementById("f-reset").addEventListener("click",function(){
    document.getElementById("q").value="";document.getElementById("f-source").value="";
    document.getElementById("f-tracks").value="1";document.getElementById("f-pop").value="0";
    document.getElementById("f-pop-v").textContent="0";
    document.getElementById("f-edges").checked=true;
    document.getElementById("f-phys").checked=false;
    network.setOptions({physics:{enabled:false}});applyFilters();collapseAll();
  });
  document.getElementById("f-expand").addEventListener("click",function(){expandAll();});
  document.getElementById("f-collapse").addEventListener("click",function(){collapseAll();});
  collapseAll();
}).catch(function(err){
  document.getElementById("counts").textContent =
    "Could not load graph.json ("+err+"). Serve this folder over http: python3 -m http.server";
});
</script>
</body></html>
"""


def render_site(catalog: dict, out_dir: str | Path,
                title: str = "Music catalog — artist similarity browser",
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
    page = SITE_TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__VIS_CDN__", VIS_CDN)
    with open(out / "index.html", "w", encoding="utf-8") as f:
        f.write(page)
    return {"dir": str(out), "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "excluded_zero_track": graph["excluded_zero_track"],
            "catalog_sha256": sha, "generated_at": generated_at}

