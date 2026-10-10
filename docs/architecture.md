# Architecture

## Modules (`src/music_catalog/`)

| Module | Owns |
|---|---|
| `data.py` | Data-dir resolution (`resolve_data_dir`, `state_path`) — code repo never owns state |
| `store.py` | File-backed registry: `normalize_name`, `ensure_artist`, `add_track` (cap 5), `merge_artists` (exact-links same titles), `dismiss_merge`; schema version 3 |
| `importer.py` | Tolerant parsers: Spotify shapes + YouTube via `youtube.py`; `import_items` + report (second source *links*, `linked_tracks`) |
| `links.py` | Dual-source consolidation: `sources` map per track, `consolidate_catalog`/`consolidate_artist` (exact auto-merge, fuzzy → `needs_review`), `coverage_report`, `attach/detach_source` |
| `youtube.py` | yt-dlp title parsing (`split_artist_title`, `- Topic` fallback, multi-artist split), `crossref_items` verdicts |
| `sources.py` | `Source` ABC: `fetch(ref)` read-only poll, `publish(tracks, dry_run=True)` stub; `YoutubeSource`, `SpotifySource`, `FakeSource`; `monitor_diff`; `write_snapshot` |
| `candidates.py` | `similarity` (feature cosine + genre Jaccard, title-overlap fallback), `score_candidate` (`popularity − similarity`), `pick_candidates(k=2)` |
| `viz.py` | Vectors (`artist_vector`, `track_vector`), dependency-free PCA (`project`), static HTML (`render_html`), `similar_artists` / `similar_tracks` |
| `cli.py` | `catalog <cmd>`: import, xref, monitor, artist, gaps, coverage, consolidate, link/unlink, candidates, similar, viz, publish |

## Data model (data repo `state/`)

```json
{"artists": [{"id": "a1", "name": "…", "aliases": [], "status": "ok|unknown|merged"}],
 "tracks": [{"id": "t1", "artist_id": "a1", "title": "…", "source": "spotify",
             "sources": {"spotify": {"id": "t1"}, "youtube": {"id": "youtube:vid"}},
             "popularity": 0, "features": {}, "genres": [], "pinned": false}]}
```

- `catalog.json` — artists/tracks/aliases (source of truth, versioned).
- `review.json` — `unknown` queue + `pending_merges` (user decides, never auto-merged).
- `snapshots/` — timestamped monitor diffs (append-only record).
- Rules: cap 5 tracks/artist, soft target 2; unknowns → review; merges explicit.
- Tracks are source-agnostic: one track carries a `sources` ref per side
  (schema v3, migrated in memory from legacy single `source`). Same
  artist + same normalized title = same track; the second source links
  instead of duplicating. Goal: every track on both sides; anything
  missing a side shows up in `catalog coverage` until linked.

## The `Source` contract (SPEC #2/#3, v2-ready)

```
fetch(ref) -> (items, raw_count)     # v1: local export file; live API in v2
publish(tracks, dry_run=True)        # v1: dry-run preview or refuse; v2: real writes
```

Monitors share one flow: `fetch` → diff (`crossref_items` for
YouTube verdicts, `monitor_diff` generically) → `write_snapshot` →
optional `import_items` apply. Adding a live backend means
subclassing `Source` (auth from env, never state); adding the v2
publisher means overriding the `dry_run=False` branch with confirm +
undo log — `cli.cmd_publish` already routes through it.

## Similarity, one definition everywhere

`candidates.similarity` (0 dissimilar … 1 near-duplicate) is the
single notion reused by gap picks (`score = popularity − similarity`
vs owned tracks), `viz` maps (same vectors, PCA-projected), and
`similar` queries (`distance = 1 − similarity`, artist-level via
mean-feature vectors). Sparse catalogs (empty `features`, no genres)
degrade gracefully: title overlap, then popularity — ordering is weak
until features land, and the code says so instead of inventing signal.

## Conventions

- Stdlib-first Python, small modules, pytest (`tests/test_*.py` mirrors modules).
- JSON on stdout, errors on stderr, exit 2 on user errors.
- No secrets in either repo; offline-capable except monitor/lookup steps.
