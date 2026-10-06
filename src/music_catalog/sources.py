"""Source interface: uniform monitor contract + v2 publish stub.

v1 is read-only monitors (SPEC #2/#3). Each source polls a playlist
reference (v1: local export JSON file) and returns normalized importer
items. The ``publish`` write path exists as an explicit stub so v2
(``catalog publish --to youtube|spotify|both``) plugs in without
reshaping core (IMPLEMENTATION_PLAN §2).

Secrets policy: live API tokens come from env only
(``SPOTIFY_TOKEN``, ``YOUTUBE_API_KEY``), never from state files.
File-based refs need no auth, so offline work and tests stay hermetic.
"""
from __future__ import annotations

import abc
import datetime
import json
import os
from pathlib import Path

from .data import resolve_data_dir


class Source(abc.ABC):
    """One playlist origin. ``fetch`` is read-only; ``publish`` is a stub."""

    name: str = "base"

    @abc.abstractmethod
    def fetch(self, ref: str | Path) -> tuple[list[dict], int]:
        """Poll ``ref``. Returns (items, raw_count); items are importer dicts."""

    def publish(self, tracks: list[dict], dry_run: bool = True) -> dict:
        """Preview (dry-run) or refuse a remote write.

        v1 has no remote-write credentials path, so only dry-run previews
        are allowed. v2 subclasses override the ``dry_run=False`` branch.
        """
        preview = {
            "source": self.name,
            "mode": "dry-run" if dry_run else "applied",
            "tracks": len(tracks),
            "sample": [
                {"id": t.get("id"), "artist_id": t.get("artist_id"), "title": t.get("title")}
                for t in tracks[:5]
            ],
        }
        if dry_run:
            return preview
        raise RuntimeError(
            f"v1 {self.name} publisher is read-only: re-run with --dry-run "
            "(v2 adds confirmed remote writes with undo log)"
        )


class YoutubeSource(Source):
    name = "youtube"

    def fetch(self, ref: str | Path) -> tuple[list[dict], int]:
        from .importer import parse_export

        return parse_export(ref, source="youtube")


class SpotifySource(Source):
    name = "spotify"

    def fetch(self, ref: str | Path) -> tuple[list[dict], int]:
        p = Path(ref) if not isinstance(ref, Path) else ref
        if not p.exists():
            # Live playlist IDs/URLs need OAuth; fail fast naming the env var.
            token = os.environ.get("SPOTIFY_TOKEN")
            if not token:
                raise FileNotFoundError(
                    f"spotify ref not a file: {ref!r}; live API needs SPOTIFY_TOKEN "
                    "(env only, never committed)"
                )
            raise NotImplementedError("live Spotify API polling lands in v2; pass an export JSON file in v1")
        from .importer import parse_export

        return parse_export(p, source="spotify")


class FakeSource(Source):
    """In-memory source for tests."""

    name = "fake"

    def __init__(self, items: list[dict] | None = None):
        self._items = list(items or [])

    def fetch(self, ref: str | Path = "<memory>") -> tuple[list[dict], int]:
        return list(self._items), len(self._items)


SOURCES: dict[str, type[Source]] = {
    "youtube": YoutubeSource,
    "spotify": SpotifySource,
    "fake": FakeSource,
}


def get_source(name: str, **kwargs) -> Source:
    try:
        cls = SOURCES[name]
    except KeyError:
        raise KeyError(f"unknown source {name!r} (known: {sorted(SOURCES)})") from None
    return cls(**kwargs)  # type: ignore[call-arg]


def monitor_diff(catalog: dict, items: list[dict]) -> dict:
    """Generic new-vs-known diff (SPEC #2/#3 contract).

    unknown: unparsed items bound for the review queue.
    known_tracks: track id already in the catalog.
    known_artist_new_track: artist registry hit, track id unseen.
    new_artist: no registry hit, would create an artist on import.
    """
    from .store import find_artist_by_name

    known_ids = {t.get("id") for t in catalog.get("tracks", [])}
    report: dict = {
        "seen": len(items),
        "known_tracks": 0,
        "known_artist_new_track": 0,
        "new_artist": 0,
        "unknown": 0,
        "details": [],
    }
    for it in items:
        if it.get("_unknown"):
            report["unknown"] += 1
            report["details"].append({"verdict": "unknown", "title": it.get("title"), "reason": it.get("reason")})
            continue
        if it.get("track_id") in known_ids:
            report["known_tracks"] += 1
            report["details"].append({"verdict": "known_track", "track_id": it.get("track_id")})
            continue
        primary = (it.get("artists") or [{}])[0].get("name", "")
        hit = find_artist_by_name(catalog, primary)
        if hit is not None:
            report["known_artist_new_track"] += 1
            report["details"].append(
                {"verdict": "known_artist_new_track", "artist": primary, "catalog_id": hit["id"], "title": it.get("title")}
            )
        else:
            report["new_artist"] += 1
            report["details"].append({"verdict": "new_artist", "artist": primary, "title": it.get("title")})
    return report


def write_snapshot(data_dir, source_name: str, report: dict) -> Path:
    """Append a timestamped monitor diff under state/snapshots/."""
    base = resolve_data_dir(data_dir)
    snap_dir = base / "state" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = snap_dir / f"{ts}-{source_name}.json"
    payload = {"source": source_name, "taken_at": ts, **report}
    # details can be large; keep snapshots countable but complete
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path
