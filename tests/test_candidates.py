"""Tests for the candidate scorer (SPEC #8, plan phase 4). Offline, synthetic vectors."""
from music_catalog.candidates import pick_candidates, similarity


def _t(tid, title, pop, features=None, genres=None):
    d = {"id": tid, "title": title, "popularity": pop, "features": features or {}}
    if genres is not None:
        d["genres"] = genres
    return d


def test_popular_dissimilar_beats_popular_duplicate():
    owned = [_t("o1", "Desert Wind", 80, {"energy": 0.9, "dance": 0.1})]
    pool = [
        _t("c1", "Desert Wind Remix", 100, {"energy": 0.9, "dance": 0.1}),  # popular near-dupe
        _t("c2", "Quiet Dune Ballad", 70, {"energy": 0.1, "dance": 0.9}),  # less popular, far
    ]
    rep = pick_candidates(owned, pool, k=2)
    assert rep["picked"][0] == "c2"
    by_id = {r["id"]: r for r in rep["ranked"]}
    assert by_id["c1"]["similarity"] > by_id["c2"]["similarity"]


def test_no_owned_tracks_is_pure_popularity():
    rep = pick_candidates([], [_t("a", "A", 30), _t("b", "B", 90), _t("c", "C", 60)], k=2)
    assert rep["picked"] == ["b", "c"]


def test_no_features_falls_back_to_title():
    owned = [_t("o1", "Midnight Thunder Live", 50)]
    pool = [
        _t("c1", "Midnight Thunder", 60),  # title-overlap sinks it
        _t("c2", "Harbor Lights", 55),
    ]
    rep = pick_candidates(owned, pool, k=2)
    assert rep["picked"][0] == "c2"


def test_genre_distance_counts():
    owned = [_t("o1", "X", 50, genres=["techno"])]
    pool = [
        _t("c1", "Y", 80, genres=["techno"]),
        _t("c2", "Z", 75, genres=["jazz"]),
    ]
    assert pick_candidates(owned, pool, k=1)["picked"] == ["c2"]


def test_owned_ids_excluded_and_tiebreak_deterministic():
    owned = [_t("o1", "X", 10)]
    pool = [_t("o1", "X", 99), _t("b", "B", 50), _t("a", "A", 50)]
    rep = pick_candidates(owned, pool, k=2)
    assert "o1" not in rep["picked"]
    assert rep["picked"] == ["a", "b"]  # same score+pop -> id order


def test_similarity_bounds():
    assert 0.0 <= similarity(_t("a", "A", 1), _t("b", "B", 1)) <= 1.0
