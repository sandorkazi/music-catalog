"""Tests for the github.io graph exporter (viz.build_graph/render_site)."""
from music_catalog.store import empty_catalog
from music_catalog.viz import acronym_for, build_graph, catalog_fingerprint, color_for, render_site


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


def test_color_for_deterministic():
    assert color_for("a1") == color_for("a1")
    assert color_for("a1").startswith("hsl(")


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
