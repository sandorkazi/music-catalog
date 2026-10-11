"""Publish config: allowlist enforcement, no secrets."""
import json

from music_catalog import publish_config as pc


def test_load_empty_ok(tmp_path, monkeypatch):
    for v in (pc.YOUTUBE_PLAYLIST_ENV, pc.SPOTIFY_PLAYLIST_ENV):
        monkeypatch.delenv(v, raising=False)
    cfg = pc.load_publish_config(None)
    assert cfg == {"youtube_playlist_id": None, "spotify_playlist_id": None}


def test_file_plus_env_override(tmp_path, monkeypatch):
    f = tmp_path / "pub.local.json"
    f.write_text(json.dumps({"youtube_playlist_id": "PL1", "spotify_playlist_id": "SP1"}),
                 encoding="utf-8")
    monkeypatch.setenv(pc.SPOTIFY_PLAYLIST_ENV, "SP2")
    cfg = pc.load_publish_config(f)
    assert (cfg["youtube_playlist_id"], cfg["spotify_playlist_id"]) == ("PL1", "SP2")
    assert pc.check_allowlist(cfg, "youtube") == "PL1"


def test_reject_secret_keys(tmp_path):
    f = tmp_path / "bad.local.json"
    f.write_text(json.dumps({"youtube_playlist_id": "PL1", "refresh_token": "x"}), encoding="utf-8")
    try:
        pc.load_publish_config(f)
    except ValueError:
        return
    raise AssertionError("secret-like key accepted")


def test_missing_allowlist_raises(monkeypatch):
    for v in (pc.YOUTUBE_PLAYLIST_ENV, pc.SPOTIFY_PLAYLIST_ENV):
        monkeypatch.delenv(v, raising=False)
    cfg = pc.load_publish_config(None)
    try:
        pc.check_allowlist(cfg, "spotify")
    except ValueError:
        return
    raise AssertionError("missing allowlist accepted")
