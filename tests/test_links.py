"""Tests for dual-source consolidation: one track, refs on both sides."""
from music_catalog.importer import import_items
from music_catalog.links import (
    attach_source,
    consolidate_catalog,
    coverage_report,
    detach_source,
    migrate_track_sources,
    normalize_track_title,
    track_has_source,
)
from music_catalog.sources import monitor_diff
from music_catalog.store import empty_catalog, empty_review


def _catalog():
    c = empty_catalog()
    c["artists"] = [{"id": "sp:known", "name": "Known Artist", "aliases": [], "status": "ok"}]
    c["tracks"] = [
        {"id": "sp:t1", "artist_id": "sp:known", "title": "Hit", "source": "spotify",
         "popularity": 90, "features": {}, "pinned": False},
    ]
    return c


def test_migrate_builds_sources_and_bumps_version():
    c = _catalog()
    c["version"] = 2
    assert migrate_track_sources(c) == 1
    t = c["tracks"][0]
    assert t["sources"] == {"spotify": {"id": "sp:t1"}}
    assert c["version"] == 3
    assert migrate_track_sources(c) == 0  # idempotent


def test_normalize_strips_feat():
    assert normalize_track_title("Wasabi (feat. X)") == normalize_track_title("Wasabi")
    assert normalize_track_title("  HIT ") == "hit"


def test_import_second_source_links_instead_of_duplicating():
    c, r = _catalog(), empty_review()
    migrate_track_sources(c)
    yt_item = {"track_id": "youtube:vid1", "title": "Hit",
               "artists": [{"id": "sp:known", "name": "Known Artist"}],
               "popularity": 0, "source": "youtube", "url": "https://youtube/watch?v=vid1",
               "channel": "SomeChannel", "video_title": "Known Artist - Hit"}
    rep = import_items(c, r, [yt_item], source="youtube")
    assert rep["linked_tracks"] == 1 and rep["added_tracks"] == 0
    assert len(c["tracks"]) == 1
    t = c["tracks"][0]
    assert set(t["sources"]) == {"spotify", "youtube"}
    assert t["popularity"] == 90  # max kept
    assert t["channel"] == "SomeChannel"


def test_import_same_source_same_title_stays_separate():
    c, r = _catalog(), empty_review()
    migrate_track_sources(c)
    dup = {"track_id": "sp:t2", "title": "Hit",
           "artists": [{"id": "sp:known", "name": "Known Artist"}],
           "popularity": 10, "source": "spotify"}
    rep = import_items(c, r, [dup], source="spotify")
    assert rep["linked_tracks"] == 0 and rep["added_tracks"] == 1
    assert len(c["tracks"]) == 2  # distinct Spotify ids: no silent remix merge
    # consolidate must not merge them either (no ref would be gained)
    assert consolidate_catalog(c)["merged"] == 0
    assert len(c["tracks"]) == 2


def test_consolidate_merges_exact_and_flags_fuzzy():
    c = _catalog()
    c["tracks"].append(
        {"id": "youtube:vid1", "artist_id": "sp:known", "title": "Hit", "source": "youtube",
         "popularity": 0, "features": {}, "pinned": False,
         "url": "https://youtube/watch?v=vid1"})
    c["tracks"].append(
        {"id": "youtube:vid2", "artist_id": "sp:known", "title": "Thunderr", "source": "youtube",
         "popularity": 0, "features": {}, "pinned": False})
    c["tracks"].append(
        {"id": "sp:t2", "artist_id": "sp:known", "title": "Thunder", "source": "spotify",
         "popularity": 50, "features": {}, "pinned": False})
    migrate_track_sources(c)
    rep = consolidate_catalog(c)
    assert rep["merged"] == 1
    assert len(c["tracks"]) == 3
    survivor = next(t for t in c["tracks"] if normalize_track_title(t["title"]) == "hit")
    assert set(survivor["sources"]) == {"spotify", "youtube"}
    assert survivor["id"] == "sp:t1"
    # near-duplicate across sources is never auto-merged, only flagged
    assert len(rep["needs_review"]) == 1
    flagged = {rep["needs_review"][0]["a"]["title"], rep["needs_review"][0]["b"]["title"]}
    assert flagged == {"Thunder", "Thunderr"}


def test_coverage_counts_and_missing_lists():
    c = _catalog()
    migrate_track_sources(c)
    rep = coverage_report(c)
    assert (rep["tracks"], rep["both"], rep["spotify_only"]) == (1, 0, 1)
    assert [e["id"] for e in rep["missing_youtube"]] == ["sp:t1"]
    assert rep["missing_spotify"] == []
    attach_source(c["tracks"][0], "youtube", {"id": "youtube:vid1"})
    rep = coverage_report(c)
    assert rep["both"] == 1 and rep["missing_youtube"] == []
    assert detach_source(c["tracks"][0], "youtube") is True
    assert track_has_source(c["tracks"][0], "youtube") is False


def test_monitor_reports_linkable_verdict():
    c = _catalog()
    migrate_track_sources(c)
    items = [{"track_id": "youtube:vid1", "title": "Hit",
              "artists": [{"id": "sp:known", "name": "Known Artist"}],
              "source": "youtube"}]
    rep = monitor_diff(c, items)
    assert rep["linkable"] == 1 and rep["known_artist_new_track"] == 0
    assert rep["details"][0]["verdict"] == "linkable"
    assert rep["details"][0]["catalog_track_id"] == "sp:t1"
