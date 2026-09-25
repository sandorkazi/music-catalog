# music-catalog

Local-first CLI engine for a curated music catalog: monitor playlists,
keep a clean merged artist registry, hold 0–5 tracks per artist
(target 2), fill gaps with popular-but-dissimilar picks, and browse
the genre/track similarity space. See `SPEC.md` for the full spec,
`IMPLEMENTATION_PLAN.md` for the phased build plan, `PROGRESS.md`
for status, `docs/` for guides.

## Repos

- Code (this repo): `git@github.com:sandorkazi/music-catalog.git`
- Data (state sync): `git@github.com:sandorkazi/music-catalog-masu.git`

State (`catalog.json`, `review.json`, `snapshots/`) lives in the
**data repo**, never here. This repo holds code + docs + tests only.

```text
~/IdeaProjects/music-catalog/       # this repo (code)
~/IdeaProjects/music-catalog-masu/  # data repo (state)
```

```bash
git clone git@github.com:sandorkazi/music-catalog.git ~/IdeaProjects/music-catalog
git clone git@github.com:sandorkazi/music-catalog-masu.git ~/IdeaProjects/music-catalog-masu
bash scripts/sync-data.sh pull   # or: pull / push / status
```

Data dir resolution (first existing wins): `$MUSIC_CATALOG_DATA_DIR`,
then sibling `../music-catalog-masu`. See
`src/music_catalog/data.py:resolve_data_dir`.

## Install

Stdlib-only, Python 3.10+. No dependencies to install.

```bash
cd ~/IdeaProjects/music-catalog
pip install -e .          # optional: puts `catalog` on PATH
# without install:
PYTHONPATH=src python3 -m music_catalog.cli --help
```

## Usage

```bash
catalog import playlist.json --dry-run        # tolerant import + report
catalog import playlist.json                  # apply to state
catalog xref yt-playlist.json --compact       # YT cross-ref (read-only)
catalog xref yt-playlist.json --apply         # import YT set
catalog monitor youtube|spotify file.json [--apply]   # poll + snapshot diff
catalog artist list --sort tracks             # registry with track counts
catalog artist review                         # pending merges + unknown queue
catalog artist merge --keep <id> --drop <id>  # explicit user-approved merge
catalog artist dismiss <id1> <id2>            # reject a merge candidate
catalog gaps [--source spotify]               # artists with < 2 tracks
catalog candidates <artist> --pool pool.json  # popular-but-dissimilar 2-pick
catalog similar <id> --by artist|track [--least]  # similarity query
catalog viz --out map.html                    # static HTML maps (no server)
catalog publish --to youtube|spotify|both --dry-run  # v1: preview only
```

Full command reference: `docs/usage.md`. Architecture and data model:
`docs/architecture.md`.

## Testing

```bash
python3 -m pytest tests/ -q     # 29 tests, offline, no secrets
bash scripts/smoke.sh           # pytest + CLI smoke on real state (read-only)
```

## Secrets

Spotify OAuth (`SPOTIFY_TOKEN`) and YouTube API keys are env /
`*.local.json` only — never committed to either repo. File-based
imports and monitors need no auth.

## v2 (later)

`catalog publish` without `--dry-run` is refused in v1 (read-only
monitors). v2 adds confirmed remote writes with undo log; the
`Source.publish(dry_run=True)` stub in `src/music_catalog/sources.py`
is the plug-in point, so core needs no reshaping.
