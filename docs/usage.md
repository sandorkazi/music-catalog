# CLI usage guide

All commands read state from the data repo (see README for resolution).
Outputs are JSON on stdout (pipe-friendly); errors go to stderr.

## Import

```bash
catalog import export.json --dry-run --source spotify
catalog import export.json --source youtube
```

Accepts Spotify playlist exports (`playlists[].tracks`, `tracks.items`,
`tracks[]`, `items[]`, bare lists) and yt-dlp flat playlists
(auto-detected via `ie_key`/`uploader*` keys, or forced with
`--source youtube`). Report: `seen / added_artists / added_tracks /
duplicate_tracks / capped_tracks / unknowns / pending_merges`.
Unknowns (unparsed titles, missing artists) go to the review queue,
never silently dropped. Per-artist cap: 5 tracks (highest popularity
wins); soft target: 2.

## Cross-reference (YouTube vs registry)

```bash
catalog xref yt.json --compact              # counts only
catalog xref yt.json --threshold 0.9        # stricter fuzzy cutoff
catalog xref yt.json --apply                # import, like `import --source youtube`
```

Verdicts per item: `matched_exact` (name/alias hit), `fuzzy`
(needs user decision — never auto-merged), `new`, `unknown`.
Read-only by default.

## Monitor (unified Source interface)

```bash
catalog monitor spotify export.json --compact
catalog monitor youtube yt.json --apply
```

Fetches via the `Source` backend (`youtube` / `spotify` / `fake`),
diffs new vs known, and appends a timestamped snapshot to
`state/snapshots/` in the data repo — including read-only runs.
Spotify refs that are not files need `SPOTIFY_TOKEN` (env only);
v1 file-based flows need no auth.

## Artist registry

```bash
catalog artist list --sort name|tracks [--source spotify|youtube]
catalog artist review                        # pending_merges + unknown
catalog artist merge --keep <id> --drop <id>
catalog artist dismiss <id1> <id2>
```

Merges are explicit and user-approved only: same-name-different-id
imports create a `pending_merges` entry instead of merging. Merge
moves tracks (pinned + most popular survive the cap of 5), unions
aliases, clears stale pending entries. Dismiss keeps both artists.

## Gaps

```bash
catalog gaps [--source youtube] [--sort name|tracks] [--compact]
```

Artists with fewer than 2 tracks, split into `zero` (0 tracks) and
`one` (1 track) lists with per-artist sources.

## Candidates (gap filling)

```bash
catalog candidates <artist-id-or-name> --pool pool.json [--limit 2]
```

Ranks a candidate pool by `popularity − similarity`: the most popular
tracks that are least like what the artist already has. `--pool`
accepts a Spotify/YouTube export (filtered to the artist when the
pool names them) or a raw JSON list of
`{id, title, popularity, features, genres}`. Prints `ranked`
(score/similarity breakdown) plus the top-`limit` `picked` ids;
select/reject by importing the ids you want (`catalog import`).
Similarity blends audio-feature cosine distance with genre Jaccard;
with no features it falls back to title overlap, then pure popularity.

## Similarity queries

```bash
catalog similar <artist-id> --by artist --top 5
catalog similar <track-id> --by track --top 5 --least
```

Same vectors as the maps and the scorer. `--least` flips to the most
dissimilar — the same notion `candidates` uses to diversify picks.
With featureless catalogs distances degrade to popularity gaps, so
treat ordering as weak until features/genres are populated.

## Visualization

```bash
catalog viz --out map.html
```

Dependency-free static HTML (inline SVG + vanilla JS, no CDN):
an artists+genres map and a tracks map from one 2D PCA over
[mean audio features, genre one-hots, popularity]. Hover for labels,
click a point to inspect. Open the file directly — no server needed.

## Publish (v1 stub)

```bash
catalog publish --to youtube|spotify|both --dry-run
```

Previews the curated set (top-2 tracks per artist by popularity).
Without `--dry-run` v1 refuses (exit 2): read-only monitors only.
