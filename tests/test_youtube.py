"""Tests for the YouTube source: title parsing + cross-reference (SPEC #2/#4)."""
import json

from music_catalog.youtube import (
    crossref_items,
    is_youtube_export,
    split_artist_title,
    yt_entry_to_item,
)


def test_split_artist_dash():
    assert split_artist_title("BENNETT – Vois sur ton chemin (Techno Mix) [Official Live Visualizer]") == (
        "BENNETT",
        "Vois sur ton chemin",
    )


def test_split_artist_feat_kept_simple():
    artist, track = split_artist_title("Oratnitza feat. Kipri - Tzurni Ochi")
    assert artist == "Oratnitza"
    assert track == "Tzurni Ochi"


def test_split_unparsed_returns_none():
    artist, _ = split_artist_title("you've NEVER heard a choir like this")
    assert artist is None


def test_topic_channel_fallback():
    entry = {"id": "abc", "title": "Born To Be Wild", "channel": "Steppenwolf - Topic"}
    item = yt_entry_to_item(entry)
    assert not item.get("_unknown")
    assert item["artists"][0]["name"] == "Steppenwolf"
    assert item["title"] == "Born To Be Wild"


def test_label_channel_stays_unknown():
    entry = {"id": "abc", "title": "Matushka Ultrafunk", "channel": "TrapMusicHDTV"}
    item = yt_entry_to_item(entry)
    assert item["_unknown"] is True
    assert item["reason"] == "unparsed-title"


def test_multi_artist_comma_split():
    entry = {"id": "x", "title": "Gabry Ponte, LUM!X, Prezioso - Thunder", "channel": "Spinnin"}
    item = yt_entry_to_item(entry)
    assert [a["name"] for a in item["artists"]] == ["Gabry Ponte", "LUM!X", "Prezioso"]


def test_is_youtube_export():
    with open("/tmp/opencode/yt-masu.json", encoding="utf-8") as f:
        assert is_youtube_export(json.load(f)) is True
    assert is_youtube_export({"playlists": []}) is False


def test_crossref_never_silently_merges():
    catalog = {"artists": [{"id": "sp:1", "name": "Kings of Leon", "aliases": [], "status": "ok"}], "tracks": []}
    items = [
        {"track_id": "youtube:1", "title": "Sex on Fire", "artists": [{"id": "youtube:kings-of-leon", "name": "Kings Of Leon"}]},
        {"track_id": "youtube:2", "title": "NEXT!", "artists": [{"id": "youtube:ncts", "name": "NCTS"}]},
        {"_unknown": True, "reason": "unparsed-title", "title": "HALF HORSE HALF MAN"},
    ]
    report = crossref_items(catalog, items)
    assert (report["matched_exact"], report["new"], report["unknown"]) == (1, 1, 1)
    assert report["details"][0]["catalog_name"] == "Kings of Leon"
