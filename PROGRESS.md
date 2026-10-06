# Progress

- [x] 0 scaffold (`feat/catalog-scaffold`) — pkg skeleton, `catalog --help`, pytest green
- [x] 1 core store + dedup (`feat/catalog-core`) — `artist merge/list/review`, alias map, unknown queue
- [x] 2 JSON import (`feat/catalog-import`) — `catalog import` + dry-run live, /tmp/playlist.json applied (986 artists / 1472 tracks)
- [x] 3 YT/Spotify monitors (`feat/catalog-monitors`) — `Source` ABC + `catalog monitor` + snapshots, `catalog publish --dry-run` stub (v1 read-only)
- [x] 4 gaps + candidates (`feat/catalog-gaps`) — `catalog gaps` + `catalog candidates` (popularity − similarity 2-pick)
- [x] 5 visualization (`feat/catalog-viz`) — `catalog viz` static HTML + `catalog similar` query
- [x] 6 polish + smoke (`feat/catalog-polish`) — README/docs, `pyproject.toml`, `scripts/smoke.sh` green
- [ ] 7 (v2) publish to YT + Spotify (`feat/catalog-publish`)

Log: last green commit + next box here on every stop.

- 2026-10-06: viz home moved to the data repo — live Pages browser
  (`docs/graph.json` + `docs/index.html`, 802 nodes/1793 edges) is
  generated natively from `music-catalog-masu/state/catalog.json` via
  `bash scripts/publish-viz.sh`; data repo carries this repo as a
  `code/` submodule (pinned generator); exports stamp
  `graph.meta` (`catalog_sha256` + `generated_at`, shown in the page
  header) and `catalog viz --out-dir <docs> --check` exits 1 when
  stale. Code-repo `docs/graph.json`+`index.html` removed (gitignored
  previews). Verified stdlib-only (no pytest/pip here): unit checks +
  render/check/stale exits + http serve OK. Next: run `pytest` where
  available, enable Pages on the data repo (Settings → Pages → docs/),
  then phase B (MusicBrainz + Wikidata no-key enrichment).
- 2026-10-06: viz loads instantly now — node positions precomputed at
  export (PCA layout into `graph.json` x/y, physics off by default
  with an opt-in toggle, straight edges, hidden-edges-on-drag).
  Republished to the data repo; `--check` still fresh (fingerprint
  covers catalog data, not layout, so the stamp stayed valid).
- 2026-10-06: degree cap (MAX_DEGREE=20, fair round-robin admission
  over tie-aware pools) + genre clusters (`cluster` per node,
  `clusters` with stored centers, bubble open-on-click,
  Expand/Collapse all). Real data: max deg 174→20, 0 isolated
  (was 113 with strict top-k), 802 nodes/3952 edges, build 0.5 s.
  Honest finding: catalog has 0 genre tags + 0 audio features, so all
  802 artists sit in `unknown` (stays flat, not bubbled) until
  `catalog tags set` curation or phase-B enrichment fills genres —
  bubbles then appear automatically on republish.

- 2026-10-06: post-v1 extras on `develop` (uncommitted) — github.io
  browser (`catalog viz --out-dir docs/`: vis-network force graph,
  845 nodes/1898 edges, acronym-in-circle, hover focus + info panel,
  filters) and phase A tags (`taxonomy.json`: 20 genres + subgenre
  parents + 33 instruments + aliases; schema v2 with in-memory
  migration; `catalog tags set/show/review/taxonomy`; artist-level
  tags feed `similar`/maps; merges union tags). Verified without
  pytest (none installed here): 32 pass, 2 pre-existing env failures
  (`test_youtube` needs `/tmp/yt-masu.json`, `test_sources` needs
  `monkeypatch`). Real-data check on a copy: shaabi-tagged
  Bahaa Sultan → nearest is shaabi-tagged Ahmed Saad. Data repo
  untouched. Next: run `pytest` where available, then phase B
  (MusicBrainz + Wikidata no-key enrichment).
- 2026-09-26: phases 3–6 done on `develop` — `sources.py` + `catalog monitor/publish`
  (`pytest` 18 passed), `candidates.py` + `catalog candidates` (24 passed),
  `viz.py` + `catalog viz/similar` (29 passed), polish (`pyproject.toml` with
  pytest `pythonpath`, rewritten README, `docs/usage.md` + `docs/architecture.md`,
  `scripts/smoke.sh` green, data repo untouched). State: 1060 artists /
  1552 tracks, 0 pending merges, 23 unknown. Next: v2 phase 7
  (`Source.publish` real writes with confirm + undo log) — NOT in v1.
- 2026-09-25: merges done — `catalog artist merge/dismiss/review/list` +
  `catalog gaps` live (`store.merge_artists`, cap-5 + pinned survive).
  Merged 12 (10 YT→Spotify, Ghymes×2, Pain×2), dismissed 1 false positive
  (DVBBS↔Borgeous collab). Now 1060 artists / 1552 tracks, 0 pending,
  23 unknown. Gaps: 65 one-track YT artists, 215 zero + 156 one overall.
  `pytest tests/` 12 passed.
- 2026-09-25: YT xref for masu set — `src/music_catalog/youtube.py` +
  `catalog xref` (read-only default, `--apply` to write); raw dump in
  data repo `extra/youtube-music-placeholder-PLM_*.json` (103 entries).
  Dry-run vs Spotify catalog: 11 matched_exact / 69 new / 23 unknown.
  `pytest tests/` 8 passed. Applied 2026-09-25: +86 artists / +80 tracks
  (1072 / 1552), 23 unknowns queued, 11 pending merges proposed.
