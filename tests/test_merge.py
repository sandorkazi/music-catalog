"""Tests for artist merge/dismiss + gaps (SPEC #4/#7)."""
import copy

from music_catalog.store import (
    artist_track_count,
    dismiss_merge,
    empty_catalog,
    empty_review,
    merge_artists,
)


def _sample():
    catalog = empty_catalog()
    review = empty_review()
    catalog["artists"] = [
        {"id": "sp:dvbbs", "name": "DVBBS", "aliases": [], "status": "ok"},
        {"id": "youtube:dvbbs", "name": "DVBBS", "aliases": [], "status": "ok"},
        {"id": "youtube:borgeous", "name": "Borgeous", "aliases": [], "status": "ok"},
    ]
    catalog["tracks"] = [
        {"id": "t1", "artist_id": "sp:dvbbs", "title": "Tsunami", "source": "spotify",
         "popularity": 80, "features": {}, "pinned": False},
        {"id": "t2", "artist_id": "youtube:dvbbs", "title": "Tsunami", "source": "youtube",
         "popularity": 0, "features": {}, "pinned": False},
        {"id": "t3", "artist_id": "youtube:borgeous", "title": "Tsunami", "source": "youtube",
         "popularity": 0, "features": {}, "pinned": False},
    ]
    review["pending_merges"] = [
        {"candidate_ids": ["sp:dvbbs", "youtube:dvbbs"], "reason": "same-name-different-id"},
        {"candidate_ids": ["sp:dvbbs", "youtube:borgeous"], "reason": "same-name-different-id"},
    ]
    return catalog, review


def test_merge_moves_tracks_and_clears_pending():
    catalog, review = _sample()
    s = merge_artists(catalog, review, "sp:dvbbs", "youtube:dvbbs")
    assert s["moved_tracks"] == 1 and s["capped_tracks"] == []
    assert artist_track_count(catalog, "sp:dvbbs") == 2
    assert artist_track_count(catalog, "youtube:dvbbs") == 0
    assert all(a["id"] != "youtube:dvbbs" for a in catalog["artists"])
    assert len(review["pending_merges"]) == 1  # borgeous entry untouched


def test_merge_enforces_cap_keep_pinned():
    catalog, review = _sample()
    for i in range(6):
        catalog["tracks"].append({"id": f"x{i}", "artist_id": "sp:dvbbs", "title": f"T{i}",
                                  "source": "spotify", "popularity": i, "features": {}, "pinned": i == 0})
    s = merge_artists(catalog, review, "sp:dvbbs", "youtube:dvbbs")
    assert artist_track_count(catalog, "sp:dvbbs") == 5
    assert any(t["pinned"] for t in catalog["tracks"] if t["artist_id"] == "sp:dvbbs")
    assert len(s["capped_tracks"]) == 3  # 8 -> cap 5


def test_dismiss_keeps_artists():
    catalog, review = _sample()
    assert dismiss_merge(review, "sp:dvbbs", "youtube:borgeous") is True
    assert len(review["pending_merges"]) == 1
    assert len(catalog["artists"]) == 3
    assert dismiss_merge(review, "sp:dvbbs", "youtube:borgeous") is False


def test_merge_unknown_id_raises():
    catalog, review = _sample()
    try:
        merge_artists(catalog, review, "sp:dvbbs", "nope")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError")
    assert len(catalog["artists"]) == 3  # untouched
