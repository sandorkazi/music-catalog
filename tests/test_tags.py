"""Tests for curated tags (phase A): taxonomy, set/validate, migration, vectors."""
import pytest

from music_catalog.store import empty_catalog
from music_catalog.tags import (
    coverage,
    effective_genres,
    effective_instruments,
    migrate_catalog,
    normalize_tag,
    parent_genre,
    set_artist_tags,
    untagged_artists,
    validate_catalog,
)
from music_catalog.viz import artist_distance, artist_vector


def _catalog():
    c = empty_catalog()
    c["artists"] = [
        {"id": "a1", "name": "Alpha", "aliases": [], "status": "ok"},
        {"id": "a2", "name": "Beta", "aliases": [], "status": "ok"},
        {"id": "a3", "name": "Gamma", "aliases": [], "status": "ok"},
    ]
    c["tracks"] = [
        {"id": "t1", "artist_id": "a1", "title": "One", "source": "spotify",
         "popularity": 50, "features": {}, "pinned": False},
        {"id": "t2", "artist_id": "a2", "title": "Two", "source": "spotify",
         "popularity": 50, "features": {}, "pinned": False},
        {"id": "t3", "artist_id": "a3", "title": "Three", "source": "spotify",
         "popularity": 50, "features": {}, "pinned": False},
    ]
    return c


def test_normalize_and_parents():
    assert normalize_tag("genres", "Techno") is None  # techno is a subgenre
    assert normalize_tag("subgenres", "Techno") == "techno"
    assert normalize_tag("subgenres", "drum and bass") == "drum-and-bass"
    assert normalize_tag("genres", "R&B") == "rnb"
    assert normalize_tag("instruments", "Voice") == "vocals"
    assert normalize_tag("genres", "not-a-genre") is None
    assert parent_genre("techno") == "electronic"
    with pytest.raises(ValueError):
        normalize_tag("nope", "x")


def test_set_auto_parent_and_reject():
    c = _catalog()
    migrate_catalog(c)
    out = set_artist_tags(c, "a1", subgenres=["techno"], instruments=["Oud"])
    assert out["genres"] == ["electronic"] and out["subgenres"] == ["techno"]
    assert out["instruments"] == ["oud"]
    with pytest.raises(ValueError):
        set_artist_tags(c, "a2", genres=["not-a-genre"])
    with pytest.raises(KeyError):
        set_artist_tags(c, "nope", genres=["pop"])


def test_migrate_idempotent_and_version():
    c = _catalog()
    assert migrate_catalog(c) > 0
    assert c["version"] == 2
    assert migrate_catalog(c) == 0  # second pass touches nothing
    assert all("tag_source" in a for a in c["artists"])


def test_effective_override_and_queue():
    c = _catalog()
    migrate_catalog(c)
    set_artist_tags(c, "a1", genres=["pop"], instruments=["vocals"])
    t1 = next(t for t in c["tracks"] if t["id"] == "t1")
    assert effective_genres(c, t1) == ["pop"]
    assert effective_instruments(c, t1) == ["vocals"]
    t1["genres"] = ["Jazz"]
    t1["instruments"] = ["piano"]
    assert effective_genres(c, t1) == ["jazz"]
    assert effective_instruments(c, t1) == ["piano"]
    queue = untagged_artists(c)
    assert {e["id"] for e in queue} == {"a2", "a3"}
    cov = coverage(c)
    assert cov["tagged"] == 1 and cov["untagged"] == 2
    assert validate_catalog(c) == []


def test_artist_vector_uses_artist_tags():
    c = _catalog()
    migrate_catalog(c)
    set_artist_tags(c, "a1", subgenres=["techno"])
    set_artist_tags(c, "a2", subgenres=["house"])
    set_artist_tags(c, "a3", subgenres=["tarab"])
    v1 = artist_vector(c, "a1")
    assert "techno" in v1["genres"] and "electronic" in v1["genres"]
    d12 = artist_distance(v1, artist_vector(c, "a2"))  # both electronic
    d13 = artist_distance(v1, artist_vector(c, "a3"))  # electronic vs arabic
    assert d12 < d13
