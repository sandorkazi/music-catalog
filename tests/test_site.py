"""Tests for the github.io graph exporter (viz.build_graph/render_site)."""
from music_catalog.store import empty_catalog
from music_catalog.viz import (
    MAX_DEGREE,
    acronym_for,
    build_graph,
    catalog_fingerprint,
    cluster_for,
    communities,
    genre_color,
    render_site,
)


def _catalog():
    c = empty_catalog()
    c["artists"] = [
        {"id": "a1", "name": "DJ Snake", "aliases": [], "status": "ok"},
        {"id": "a2", "name": "Mohamed Hamaki", "aliases": [], "status": "ok"},
        {"id": "a3", "name": "GIMS", "aliases": [], "status": "ok"},
        {"id": "a4", "name": "Nobody", "aliases": [], "status": "ok"},  # zero-track: excluded
    ]
    c["tracks"] = [
        {"id": "t1", "artist_id": "a1", "title": "One", "source": "spotify",
         "popularity": 80, "features": {"energy": 0.9}, "genres": ["pop"]},
        {"id": "t2", "artist_id": "a2", "title": "Two", "source": "spotify",
         "popularity": 70, "features": {"energy": 0.85}, "genres": ["pop"]},
        {"id": "t3", "artist_id": "a3", "title": "Three", "source": "youtube",
         "popularity": 60, "features": {"energy": 0.1}, "genres": ["jazz"]},
    ]
    return c


def test_acronym_for():
    assert acronym_for("DJ Snake") == "DS"
    assert acronym_for("Mohamed Hamaki") == "MH"
    assert acronym_for("GIMS") == "GI"
    assert acronym_for("") == "?"
    assert acronym_for("Édith Piaf") == "EP"


def test_genre_color_taxonomy_hue_and_gray():
    assert genre_color("pop").startswith("hsl(")
    assert genre_color("pop") != genre_color("rock")
    assert genre_color("pop") == genre_color("pop")
    assert genre_color("other") == genre_color("unknown") == "hsl(0, 0%, 74%)"
    assert genre_color("group-a1") == "hsl(0, 0%, 74%)"


def test_build_graph_knn_and_exclusion():
    g = build_graph(_catalog(), k=2)
    assert len(g["nodes"]) == 3
    assert g["excluded_zero_track"] == 1
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"a1", "a2", "a3"}
    assert all(n["acronym"] for n in g["nodes"])
    # undirected dedup: <= 3*2 pairs, >= 2 edges for 3 nodes at k=2
    assert 2 <= len(g["edges"]) <= 3
    for e in g["edges"]:
        assert e["a"] in ids and e["b"] in ids and e["a"] != e["b"]


def test_build_graph_positions_precomputed_and_deterministic():
    g1 = build_graph(_catalog(), k=2)
    g2 = build_graph(_catalog(), k=2)
    for n in g1["nodes"]:
        assert isinstance(n["x"], float) and isinstance(n["y"], float)
    assert [(n["id"], n["x"], n["y"]) for n in g1["nodes"]] == \
        [(n["id"], n["x"], n["y"]) for n in g2["nodes"]]


def _hub_farm(n=30):
    """Identical vectors -> total distance ties -> mega-hub without a cap."""
    c = empty_catalog()
    c["artists"] = [{"id": f"a{i:02d}", "name": f"Band {i}",
                     "aliases": [], "status": "ok"} for i in range(n)]
    c["tracks"] = [{"id": f"t{i:02d}", "artist_id": f"a{i:02d}",
                    "title": "Same", "source": "spotify", "popularity": 50,
                    "features": {}, "genres": []} for i in range(n)]
    return c


def test_max_degree_cap():
    from collections import Counter
    g = build_graph(_hub_farm(), k=3)
    deg = Counter()
    for e in g["edges"]:
        deg[e["a"]] += 1
        deg[e["b"]] += 1
    assert max(deg.values()) <= MAX_DEGREE
    assert set(deg) == {f"a{i:02d}" for i in range(30)}  # nobody isolated
    g2 = build_graph(_hub_farm(), k=3)
    assert g["edges"] == g2["edges"]


def test_communities_deterministic_and_covering():
    g = build_graph(_hub_farm(), k=3)
    ids = [n["id"] for n in g["nodes"]]
    c1 = communities(ids, g["edges"])
    c2 = communities(ids, g["edges"])
    assert c1 == c2
    assert set(c1) == set(ids)
    # every community with 2+ members becomes a bubble with a stored center
    bubbles = {c["id"] for c in g["clusters"]}
    assert {n["cluster"] for n in g["nodes"]} <= bubbles


def test_untagged_artists_bubble_by_community_not_unknown():
    g = build_graph(_hub_farm(), k=3)
    assert not any(n["cluster"] == "unknown" for n in g["nodes"])
    assert any(n["cluster"].startswith("group-") for n in g["nodes"])
    assert all(n["color"] == "hsl(0, 0%, 74%)" for n in g["nodes"])


def test_big_blobs_split_into_bounded_leaves():
    big = _hub_farm(n=100)
    g = build_graph(big, k=3)
    kids = {c["id"] for c in g["clusters"] if c.get("parent")}
    childless = [c for c in g["clusters"] if c["id"] not in {c.get("parent") for c in g["clusters"] if c.get("parent")}]
    # every bubble that opens straight to artists holds <= 40 of them
    assert all(c["count"] <= 40 for c in childless), [(c["id"], c["count"]) for c in childless]
    # every artist sits in a childless (directly openable) bubble
    assert {n["cluster"] for n in g["nodes"]} == {c["id"] for c in childless}
    labels = [c["label"] for c in g["clusters"]]
    assert len(set(labels)) == len(labels)  # unique bubble labels
    g2 = build_graph(big, k=3)
    assert g["clusters"] == g2["clusters"]


def test_tagged_artists_keep_genre_bubble_and_hue():
    g = build_graph(_catalog(), k=2)
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["a1"]["cluster"] == "pop"  # track genre vote
    assert by_id["a3"]["cluster"] == "jazz"
    assert by_id["a1"]["color"] == genre_color("pop") != "hsl(0, 0%, 74%)"


def test_cluster_for_rolls_up_and_defaults():
    assert cluster_for({"shaabi", "pop"}) in ("arabic", "pop")  # vote, deterministic
    assert cluster_for({"shaabi"}) == "arabic"  # subgenre -> parent
    assert cluster_for({"pop"}) == "pop"  # top-level stays
    assert cluster_for({"zz-not-a-genre"}) == "other"
    assert cluster_for(set()) == "unknown"


def test_build_graph_clusters_cover_nodes_with_stored_centers():
    g1 = build_graph(_catalog(), k=2)
    ids = {c["id"] for c in g1["clusters"]}
    assert {n["cluster"] for n in g1["nodes"]} <= ids
    assert {n["top"] for n in g1["nodes"]} <= ids | {c.get("parent") for c in g1["clusters"] if c.get("parent")}
    by_id = {n["id"]: n for n in g1["nodes"]}
    kids: dict = {}
    for c in g1["clusters"]:
        if c.get("parent"):
            kids.setdefault(c["parent"], []).append(c["id"])
    for c in g1["clusters"]:
        if c.get("parent") or c["id"] not in kids:
            members = [by_id[n["id"]] for n in g1["nodes"] if n["cluster"] == c["id"]]
        else:  # split top: members are the leaves' artists
            members = [by_id[n["id"]] for n in g1["nodes"] if n["top"] == c["id"]]
        assert c["count"] == len(members) >= 1
        assert c["x"] == round(sum(m["x"] for m in members) / len(members), 1)
        assert c["y"] == round(sum(m["y"] for m in members) / len(members), 1)
        if c.get("parent"):
            assert c["parent"] in ids
            assert all(by_id[n["id"]]["top"] == c["parent"] for n in members)
    g2 = build_graph(_catalog(), k=2)
    assert g1["clusters"] == g2["clusters"]


def test_edge_trim_budgets_and_local_weights():
    from music_catalog.viz import TRIM_BUDGETS
    g = build_graph(_hub_farm(), k=3)
    assert all(e["lvl"] in (0, 1, 2) for e in g["edges"])
    assert all(0.0 < e["w"] <= 1.0 for e in g["edges"])
    assert not any(k.startswith("rank_") for e in g["edges"] for k in e)
    per_node: dict = {}
    for e in g["edges"]:
        for u in (e["a"], e["b"]):
            per_node.setdefault(u, {}).setdefault(e["lvl"], 0)
            per_node[u][e["lvl"]] += 1
    # union rule: a node may exceed budget via partner-kept edges, but its
    # own closest link of each kind always survives (no trim isolates)
    degs: dict = {}
    for e in g["edges"]:
        degs[e["a"]] = degs.get(e["a"], 0) + 1
        degs[e["b"]] = degs.get(e["b"], 0) + 1
    assert set(degs) == {n["id"] for n in g["nodes"]}
    assert max(degs.values()) <= MAX_DEGREE
    assert TRIM_BUDGETS == {0: 4, 1: 2, 2: 1}


def test_render_site_writes_graph_and_page(tmp_path):
    summary = render_site(_catalog(), tmp_path / "site")
    assert summary["nodes"] == 3
    assert (tmp_path / "site" / "graph.json").exists()
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "vis-network" in page and "graph.json" in page


def test_catalog_fingerprint_stable_and_sensitive():
    c = _catalog()
    assert catalog_fingerprint(c) == catalog_fingerprint(_catalog())
    other = _catalog()
    other["tracks"] = other["tracks"] + [
        {"id": "t9", "artist_id": "a3", "title": "Extra", "source": "spotify",
         "popularity": 10, "features": {}, "genres": []},
    ]
    assert catalog_fingerprint(other) != catalog_fingerprint(c)


def test_render_site_stamps_meta(tmp_path):
    import json

    summary = render_site(_catalog(), tmp_path / "site")
    g = json.loads((tmp_path / "site" / "graph.json").read_text(encoding="utf-8"))
    assert g["meta"]["catalog_sha256"] == summary["catalog_sha256"]
    assert g["meta"]["catalog_sha256"] == catalog_fingerprint(_catalog())
    assert g["meta"]["generated_at"]
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "freshnessLine" in page and "catalog_sha256" in page


def test_spread_separates_stacks_deterministically():
    from music_catalog.viz import _spread
    import math
    stacked = [(100.0, 100.0)] * 10 + [(500.0, 500.0)]
    a = _spread(stacked)
    b = _spread(stacked)
    assert a == b  # deterministic
    for i in range(10):
        for j in range(i + 1, 10):
            dx, dy = a[i][0] - a[j][0], a[i][1] - a[j][1]
            assert math.hypot(dx, dy) >= 30.0 - 1e-9
    assert a[10] == (500.0, 500.0)  # isolated point untouched


def test_rendered_page_freezes_nodes_and_dims_on_filter(tmp_path):
    summary = render_site(_catalog(), tmp_path / "site")
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "fixed:{x:true,y:true}" in page
    assert "dragNodes:false" in page
    assert "f-phys" not in page
    assert 'id="f-edges" type="checkbox"> edges' in page  # edges off by default
    assert "hidden:!document.getElementById" in page
    for marker in ("setHL", "setPinned", "setWiggle", "DIM", "expandAll", "collapseAll",
                   "openBubble", "collapseTop", "collapseSub", "n.top", "e.w"):
        assert marker in page, marker
