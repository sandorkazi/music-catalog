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

## Tags (genres, subgenres, instruments)

```bash
catalog tags taxonomy --kind genres       # controlled vocabulary (20 genres)
catalog tags taxonomy --kind subgenres    # each maps to exactly one parent
catalog tags taxonomy --kind instruments  # 33 instruments
catalog tags set "Bahaa Sultan" --subgenre shaabi --instrument vocals
catalog tags show "Bahaa Sultan"
catalog tags review --limit 50            # coverage + untagged queue + violations
```

Manual curation against `src/music_catalog/taxonomy.json` (schema v2,
additive — v1 state migrates in memory, persisted on next write).
Setting a subgenre auto-adds its parent; unknown tags are rejected
(exit 2) instead of stored. Tracks may carry `genres`/`instruments`
as an override, else the artist's tags apply. Artist-level tags feed
`similar`/`candidates`/both maps immediately; instruments are
display/filter metadata and don't affect scoring yet.

## GitHub Pages browser (lives in the data repo)

The live artist-similarity browser is served from the **data repo**:
`docs/graph.json` (kNN similarity graph over in-catalog artists, same
`artist_distance` the CLI `similar` query uses) plus `docs/index.html`
(vis-network via CDN: force layout, wheel-zoom, hover → neighbourhood
highlight + camera focus + info panel, click to pin, filters for
search/source/track-count/popularity). Node positions are precomputed
at export (same PCA projection as the static maps), so the page
renders instantly, every node frozen at its stored position
(export also de-collides overlaps): filters only fade
non-matches to transparent + unclickable, nothing ever moves.
Edges are degree-capped (closest-first, tie-aware pools so no
artist is starved behind a hub) and hidden until hover — hover a
node to light its neighbourhood, tick the edges box to show all.
Artists start grouped in similarity bubbles (label propagation,
precomputed centers, stored in the export) — click one for
subgroup bubbles (no bubble opens to more than 40 artists),
again for artists, or use Expand all / Collapse all. Node colors
follow the genre taxonomy (gray = untagged); tagged artists
migrate to genre bubbles automatically as `catalog tags set`
curation (or a future enrichment pass) fills genres in. Nodes are acronym-in-circle
placeholders — no artwork is hosted or copied. The export is generated
**natively from that repo's own `state/catalog.json`** — no data is
duplicated across repos; the code repo only provides the generator.

```bash
bash scripts/publish-viz.sh            # render into <data-repo>/docs + commit there
bash scripts/publish-viz.sh --check    # validate the published site is fresh (exit 1 if stale)
python3 -m http.server -d <data-repo>/docs 8000   # local preview (file:// blocks graph.json)
```

Each export stamps `graph.json → meta` (`catalog_sha256` +
`generated_at`); the page header shows "updated … · catalog …", and
`--check` compares the stamp against the current catalog, so a stale
site is detectable without rebuilding. Re-publish whenever the
catalog changes. Enable Pages with `Settings → Pages → Deploy from
branch → docs/` **on the data repo**
(`https://<user>.github.io/music-catalog-masu/`).

The data repo carries this code repo as a `code/` submodule, so any
data checkout pins the exact generator version its `docs/` was built
with. Local throwaway preview without touching the data repo:

```bash
catalog viz --out-dir /tmp/viz-preview
python3 -m http.server -d /tmp/viz-preview 8000
```

## Publish (v1 stub)

```bash
catalog publish --to youtube|spotify|both --dry-run
```

Previews the curated set (top-2 tracks per artist by popularity).
Without `--dry-run` v1 refuses (exit 2): read-only monitors only.
