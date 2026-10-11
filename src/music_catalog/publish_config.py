"""Publish config: allowlist + token env names. No secrets stored here.

v2 publishers only ever write to the two configured playlist IDs.
Tokens come from env only, never from state or the code repo.
Local IDs file (``*.local.json``, git-ignored) holds playlist IDs only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Env names (tokens only, never passwords).
SPOTIFY_REFRESH_ENV = "SPOTIFY_REFRESH"
SPOTIFY_CLIENT_ENV = "SPOTIFY_CLIENT_ID"
SPOTIFY_SECRET_ENV = "SPOTIFY_CLIENT_SECRET"
YOUTUBE_REFRESH_ENV = "YOUTUBE_REFRESH"
YOUTUBE_CLIENT_ENV = "YOUTUBE_CLIENT_ID"
YOUTUBE_SECRET_ENV = "YOUTUBE_CLIENT_SECRET"

YOUTUBE_PLAYLIST_ENV = "MUSIC_CATALOG_YOUTUBE_PLAYLIST"
SPOTIFY_PLAYLIST_ENV = "MUSIC_CATALOG_SPOTIFY_PLAYLIST"

# Minimal scopes (documented, requested by the token helper scripts).
SPOTIFY_SCOPES = "playlist-read-private playlist-modify-public playlist-modify-private"
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.force-ssl"


def load_publish_config(path: str | os.PathLike | None = None) -> dict:
    """Load playlist-ID allowlist. Env overrides file.

    File shape: {"youtube_playlist_id": "PL...", "spotify_playlist_id": "..."}.
    Returns {"youtube_playlist_id": str|None, "spotify_playlist_id": str|None}.
    Never reads tokens from the file.
    """
    cfg: dict = {"youtube_playlist_id": None, "spotify_playlist_id": None}
    if path:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"publish config not a dict: {path}")
            for key in ("youtube_playlist_id", "spotify_playlist_id"):
                if data.get(key):
                    cfg[key] = str(data[key])
            for bad in ("password", "secret", "token", "refresh"):
                if any(bad in str(k).lower() for k in data):
                    raise ValueError(f"publish config must hold IDs only (found {bad!r}-like key)")
    if os.environ.get(YOUTUBE_PLAYLIST_ENV):
        cfg["youtube_playlist_id"] = os.environ[YOUTUBE_PLAYLIST_ENV]
    if os.environ.get(SPOTIFY_PLAYLIST_ENV):
        cfg["spotify_playlist_id"] = os.environ[SPOTIFY_PLAYLIST_ENV]
    return cfg


def check_allowlist(cfg: dict, target: str) -> str:
    """Return the allowlisted playlist ID for target or raise."""
    key = f"{target}_playlist_id"
    pid = cfg.get(key)
    if not pid:
        raise ValueError(
            f"no allowlisted {target} playlist id: set {key} in config file "
            f"or ${YOUTUBE_PLAYLIST_ENV if target == 'youtube' else SPOTIFY_PLAYLIST_ENV}"
        )
    return str(pid)
