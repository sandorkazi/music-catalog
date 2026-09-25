# music-catalog

Music catalog engine: local-first CLI tool (see `SPEC.md`, `IMPLEMENTATION_PLAN.md`, `PROGRESS.md`).

## Repos

- Code (this repo): `git@github.com:sandorkazi/music-catalog.git`
- Data (state sync): `git@github.com:sandorkazi/music-catalog-masu.git`

State (catalog/review/snapshots) lives in the **data repo**, not here.
This repo contains code + docs + tests only.

## Data checkout layout

```text
~/IdeaProjects/music-catalog/       # this repo (code)
~/IdeaProjects/music-catalog-masu/  # data repo (state)
```

Clone both side by side:

```bash
git clone git@github.com:sandorkazi/music-catalog.git ~/IdeaProjects/music-catalog
git clone git@github.com:sandorkazi/music-catalog-masu.git ~/IdeaProjects/music-catalog-masu
bash scripts/sync-data.sh pull   # or: pull / push / status
```

## Data dir resolution

Order (first existing wins):

1. `$MUSIC_CATALOG_DATA_DIR` (explicit override, e.g. a worktree checkout)
2. Sibling `../music-catalog-masu` (default local layout above)
3. `./state` fallback is **not** used — state must come from the data repo

See `src/music_catalog/data.py:resolve_data_dir`.

Secrets (Spotify OAuth, YouTube API key) are env / `*.local.json` only,
never committed to either repo.
