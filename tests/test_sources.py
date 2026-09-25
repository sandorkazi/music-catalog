"""Tests for the Source interface (SPEC #2/#3, plan phase 3). No network, no secrets."""
import json

import pytest

from music_catalog.sources import (
    FakeSource,
    SpotifySource,
    YoutubeSource,
    get_source,
    monitor_diff,
    write_snapshot,
)
from music_catalog.store import empty_catalog


def _catalog():
    c = empty_catalog()
    c["artists"] = [{"id": "sp:known", "name": "Known Artist", "aliases": [], "status": "ok"}]
    c["tracks"] = [
        {"id": "sp:t1", "artist_id": "sp:known", "title": "Hit", "source": "spotify",
         "popularity": 90, "features": {}, "pinned": False}
    ]
    return c


def test_fake_fetch_and_diff():
    items = [
        {"track_id": "sp:t1", "title": "Hit", "artists": [{"id": "sp:known", "name": "Known Artist"}]},
        {"track_id": "sp:t2", "title": "New Hit", "artists": [{"id": "sp:known", "name": "Known Artist"}]},
        {"track_id": "sp:t3", "title": "Debut", "artists": [{"id": "sp:new", "name": "Brand New"}]},
        {"_unknown": True, "reason": "missing-title", "raw_id": "x"},
    ]
    src = FakeSource(items)
    fetched, raw = src.fetch("<memory>")
    assert raw == 4
    rep = monitor_diff(_catalog(), fetched)
    assert (rep["known_tracks"], rep["known_artist_new_track"], rep["new_artist"], rep["unknown"]) == (1, 1, 1, 1)


def test_publish_dry_run_ok_and_real_write_refused():
    src = FakeSource([])
    prev = src.publish([{"id": "t", "artist_id": "a", "title": "T"}], dry_run=True)
    assert prev["mode"] == "dry-run" and prev["tracks"] == 1
    with pytest.raises(RuntimeError):
        src.publish([], dry_run=False)


def test_get_source_registry():
    assert isinstance(get_source("youtube"), YoutubeSource)
    assert isinstance(get_source("spotify"), SpotifySource)
    assert isinstance(get_source("fake", items=[]), FakeSource)
    with pytest.raises(KeyError):
        get_source("deezer")


def test_file_sources_read_tmp_exports(tmp_path):
    yt = {"entries": [{"id": "v1", "title": "Known Artist - New Hit", "channel": "SomeChannel"}]}
    yp = tmp_path / "yt.json"
    yp.write_text(json.dumps(yt), encoding="utf-8")
    items, raw = YoutubeSource().fetch(yp)
    assert raw == 1 and items[0]["title"] == "New Hit"

    sp = {"playlists": [{"tracks": [{"track": {
        "id": "sp:t9", "name": "Debut",
        "artists": [{"id": "sp:new", "name": "Brand New"}],
        "popularity": 10, "album": {"name": "A"},
        "external_urls": {"spotify": "https://x"}}}]}]}
    pp = tmp_path / "sp.json"
    pp.write_text(json.dumps(sp), encoding="utf-8")
    items, raw = SpotifySource().fetch(pp)
    assert raw == 1 and items[0]["track_id"] == "sp:t9"


def test_spotify_missing_file_needs_token(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOTIFY_TOKEN", raising=False)
    with pytest.raises(FileNotFoundError):
        SpotifySource().fetch(tmp_path / "nope.json")


def test_write_snapshot(tmp_path):
    d = tmp_path / "data"
    (d / "state").mkdir(parents=True)
    p = write_snapshot(d, "fake", {"seen": 1})
    assert p.exists() and p.parent.name == "snapshots"
    assert json.loads(p.read_text(encoding="utf-8"))["source"] == "fake"
