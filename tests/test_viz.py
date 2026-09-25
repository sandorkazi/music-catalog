"""Tests for similarity-space viz (SPEC #9, plan phase 5). Offline, synthetic."""
import pytest

from music_catalog.store import empty_catalog
from music_catalog.viz import (
    project,
    render_html,
    similar_artists,
    similar_tracks,
)


def _catalog():
    c = empty_catalog()
    c["artists"] = [
        {"id": "a1", "name": "Alpha", "aliases": [], "status": "ok"},
        {"id": "a2", "name": "Beta", "aliases": [], "status": "ok"},
        {"id": "a3", "name": "Gamma", "aliases": [], "status": "ok"},
    ]
    c["tracks"] = [
        {"id": "t1", "artist_id": "a1", "title": "One", "source": "spotify",
         "popularity": 80, "features": {"energy": 0.9, "dance": 0.1}, "genres": ["techno"]},
        {"id": "t2", "artist_id": "a2", "title": "Two", "source": "spotify",
         "popularity": 70, "features": {"energy": 0.85, "dance": 0.15}, "genres": ["techno"]},
        {"id": "t3", "artist_id": "a3", "title": "Three", "source": "spotify",
         "popularity": 60, "features": {"energy": 0.1, "dance": 0.9}, "genres": ["jazz"]},
    ]
    return c


def test_project_deterministic_2d():
    from music_catalog.viz import artist_vector

    c = _catalog()
    vecs = [artist_vector(c, a["id"]) for a in c["artists"]]
    p1, p2 = project(vecs), project(vecs)
    assert len(p1) == 3 and all(len(p) == 2 for p in p1)
    assert p1 == p2


def test_project_empty_features_never_crashes():
    c = empty_catalog()
    c["artists"] = [{"id": f"a{i}", "name": f"A{i}", "aliases": [], "status": "ok"} for i in range(5)]
    from music_catalog.viz import artist_vector

    pts = project([artist_vector(c, a["id"]) for a in c["artists"]])
    assert len(pts) == 5


def test_similar_artists_orders_by_distance():
    rows = similar_artists(_catalog(), "a1", top=2)
    assert [r["id"] for r in rows] == ["a2", "a3"]
    least = similar_artists(_catalog(), "a1", top=2, least=True)
    assert [r["id"] for r in least] == ["a3", "a2"]


def test_similar_tracks_and_unknown_ids():
    rows = similar_tracks(_catalog(), "t1", top=2)
    assert rows[0]["id"] == "t2"
    with pytest.raises(KeyError):
        similar_artists(_catalog(), "nope")
    with pytest.raises(KeyError):
        similar_tracks(_catalog(), "nope")


def test_render_html_has_both_views_and_escaping():
    c = _catalog()
    c["artists"][0]["name"] = "Al<pha>&"
    out = render_html(c)
    assert "Artists + genres" in out and "<h2>Tracks</h2>" in out
    assert "Al&lt;pha&gt;&amp;" in out
    assert out.count("<svg") == 2
