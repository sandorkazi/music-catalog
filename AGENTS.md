# music-catalog (code repo — opencode entry point)

Open opencode in this repo. Data lives in the sibling checkout
`../music-catalog-masu` (branch `develop`).

## Rules

- This repo: code + docs + tests only. Never put `catalog.json`,
  `review.json`, `snapshots/` or any `state/` here
  (`.gitignore` already excludes `state/`).
- Data repo (`../music-catalog-masu`): all state under `state/`
  (`catalog.json`, `review.json`, `snapshots/`). Raw dumps go to `extra/`.
  The live Pages browser lives in `docs/` (`graph.json` + `index.html`,
  generated natively from `state/` via `bash scripts/publish-viz.sh`;
  freshness via `graph.json → meta` + `catalog viz --out-dir docs --check`).
  Both branches are deployed as one site: `gh-pages` branch, root = main's
  `docs/`, `develop/` = develop's `docs/`, rebuilt by
  `.github/workflows/pages.yml` (tracked in both repos; runs in the data
  repo). Pages setting: Deploy from branch → `gh-pages` / (root).
  No hand-written code there — only exceptions are the generated `docs/`
  site, the `code/` submodule pinning this repo's generator, and the
  `pages.yml` workflow (whose template lives here).
  Secrets never in either repo (env / `*.local.json` only, both git-ignored).
- Data-dir resolution (first existing wins): `$MUSIC_CATALOG_DATA_DIR`,
  then sibling `../music-catalog-masu`
  (see `src/music_catalog/data.py:resolve_data_dir`). No env needed
  in the standard side-by-side layout.
- Both repos are on `develop`, clean and in sync with `origin/develop`.
  Commit/push each repo separately (`git -C <dir> ...`).

## Sync data repo (from this repo root)

```bash
bash scripts/sync-data.sh status  # or: pull / push
```

## Run / test (from this repo root)

```bash
PYTHONPATH=src python3 -m music_catalog.cli --help
PYTHONPATH=src python3 -m pytest tests/ -q
bash scripts/smoke.sh   # pytest + read-only CLI checks, no writes
```

Full CLI reference: `docs/usage.md`.
Spec: `SPEC.md`. Plan/progress:
`IMPLEMENTATION_PLAN.md`, `PROGRESS.md`.
