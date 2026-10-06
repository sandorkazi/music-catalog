"""YouTube source: yt-dlp flat-playlist JSON -> catalog items + cross-reference.

Cross-reference contract (SPEC #4): normalize names, match against the
existing (Spotify-built) artist registry. Exact/alias hits merge; anything
else goes to the review queue, never silently merged.
"""
from __future__ import annotations

import difflib
import re

from .store import find_artist_by_name, normalize_name

# "(Official Video)", "[HQ Audio]", "Slowed + Reverb", "| Ministry of Sound" …
_BRACKET_RE = re.compile(r"\s*[\(\[][^()\[\]]*[\)\]]")
_PIPE_TAIL_RE = re.compile(r"\s*[|\u2502]\s*.*$")
_HASH_TAIL_RE = re.compile(r"\s*#\w.*$")
_SEP_RE = re.compile(r"\s+[-\u2013\u2014|:\u2502]\s+")
_FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring|with)\s+.*$", re.IGNORECASE)
_TOPIC_RE = re.compile(r"\s+-\s+topic$", re.IGNORECASE)
_MULTI_RE = re.compile(r"\s*(?:&|and|x|vs\.?|,)\s+", flags=re.IGNORECASE)


def clean_title_bit(s: str) -> str:
    s = _PIPE_TAIL_RE.sub("", s or "")
    s = _HASH_TAIL_RE.sub("", s or "")
    # strip bracketed suffixes repeatedly: "X (Official Video) [HQ]" -> "X"
    prev = None
    while prev != s:
        prev = s
        s = _BRACKET_RE.sub("", s).strip()
    return re.sub(r"\s+", " ", s).strip(" -–—|:;")


def split_artist_title(video_title: str) -> tuple[str | None, str]:
    """Guess (artist, track) from a free-form YouTube video title.

    Returns (None, cleaned_title) when no artist separator is found —
    caller must route that to the review queue as unknown.
    """
    t = clean_title_bit(video_title)
    # "Artist feat. X - Title": artist part is before the dash; drop feats
    # from the *track* side only via clean step below, keep artist simple.
    m = _SEP_RE.search(t)
    if not m:
        # "Artist feat. X - ..." without dash handled above; "Oratnitza feat. Kipri - Tzurni Ochi" has one.
        # Last resort: "Artist - ..." with odd spacing already covered. Give up.
        # Also try "by Artist" / channel fallback is done by caller.
        feat = re.split(r"\s+-\s+", t, maxsplit=1)
        if len(feat) != 2:
            return None, t
        artist, track = (x.strip() for x in feat)
    else:
        artist, track = t[: m.start()].strip(), t[m.end():].strip()
    # "Oratnitza feat. Kipri" -> primary "Oratnitza", keep feat in aliases later
    artist = _FEAT_RE.sub("", artist).strip()
    track = _FEAT_RE.sub("", track).strip() if "feat" in track.lower() and "(" in video_title else track
    if not artist or not track:
        return None, clean_title_bit(video_title)
    return artist, track


def yt_entry_to_item(entry: dict) -> dict | None:
    """Normalize one yt-dlp flat-playlist entry to an importer item dict."""
    if not isinstance(entry, dict):
        return None
    vid = entry.get("id")
    title = entry.get("title") or entry.get("fulltitle") or ""
    channel = entry.get("channel") or entry.get("uploader") or ""
    url = entry.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
    artist_guess, track_guess = split_artist_title(title)
    if artist_guess is None:
        # Auto-generated artist channels ("Steppenwolf - Topic"): the channel
        # IS the artist and the video title IS the track. Labels/publishers
        # ("Spinnin' Records", "TrapMusicHDTV") must NOT take this path.
        if channel and _TOPIC_RE.search(channel):
            artist_guess = _TOPIC_RE.sub("", channel).strip()
            track_guess = clean_title_bit(title)
        else:
            return {
                "_unknown": True,
                "reason": "unparsed-title",
                "title": clean_title_bit(title),
                "channel": channel,
                "raw_id": vid,
                "source": "youtube",
            }
    artists = [{"id": f"youtube:{normalize_name(artist_guess).replace(' ', '-')}", "name": artist_guess}]
    # keep collaborators visible: "A & B - T" / "A, B, C - T" / "A feat. B - T"
    extra = [x for x in _MULTI_RE.split(artist_guess) if x.strip()]
    if len(extra) > 1:
        artists = [{"id": f"youtube:{normalize_name(x).replace(' ', '-')}", "name": x} for x in extra]
    return {
        "track_id": f"youtube:{vid}" if vid else f"youtube:local-{normalize_name(track_guess).replace(' ', '-')}",
        "title": track_guess,
        "artists": artists,
        "popularity": 0,
        "album": None,
        "added_at": None,
        "source": "youtube",
        "url": url,
        "channel": channel,
        "video_title": title,
    }


def iter_yt_entries(data) -> list[dict]:
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return [e for e in data["entries"] if isinstance(e, dict)]
    if isinstance(data, list):
        return [e for e in data if isinstance(e, dict) and ("uploader" in e or "channel" in e or "ie_key" in e)]
    raise ValueError("not a yt-dlp playlist shape (expected {'entries': [...]})")


def is_youtube_export(data) -> bool:
    try:
        entries = (data.get("entries", None) if isinstance(data, dict) else None)
    except AttributeError:
        return False
    if not isinstance(entries, list) or not entries:
        return False
    probe = next((e for e in entries if isinstance(e, dict)), {})
    return any(k in probe for k in ("ie_key", "uploader", "uploader_id", "channel_id", "webpage_url"))


def crossref_items(catalog: dict, items: list[dict], fuzzy_threshold: float = 0.86, fuzzy_top: int = 3) -> dict:
    """Match parsed YT items against the catalog artist registry (read-only).

    Returns a report with per-item verdicts:
      matched_exact  — normalized name or alias hit
      fuzzy          — close names, needs user decision (never auto-merge)
      new            — no hit; would create an artist on import
      unknown        — unparsed title; would go to review queue
    """
    names = [a.get("name", "") for a in catalog.get("artists", [])]
    norm_index = {normalize_name(n): n for n in names}
    report = {
        "seen": len(items),
        "matched_exact": 0,
        "fuzzy": 0,
        "new": 0,
        "unknown": 0,
        "details": [],
    }
    for it in items:
        if it.get("_unknown"):
            report["unknown"] += 1
            report["details"].append({"verdict": "unknown", **{k: it.get(k) for k in ("title", "reason", "channel", "raw_id")}})
            continue
        primary = it["artists"][0]["name"]
        hit = find_artist_by_name(catalog, primary)
        if hit is not None:
            report["matched_exact"] += 1
            report["details"].append(
                {"verdict": "matched_exact", "yt_artist": primary, "catalog_name": hit["name"],
                 "catalog_id": hit["id"], "yt_title": it["title"]}
            )
            continue
        norm = normalize_name(primary)
        candidates = difflib.get_close_matches(norm, list(norm_index), n=fuzzy_top, cutoff=fuzzy_threshold)
        if candidates:
            report["fuzzy"] += 1
            report["details"].append(
                {"verdict": "fuzzy", "yt_artist": primary, "yt_title": it["title"],
                 "candidates": [norm_index[c] for c in candidates]}
            )
        else:
            report["new"] += 1
            report["details"].append({"verdict": "new", "yt_artist": primary, "yt_title": it["title"]})
    return report
