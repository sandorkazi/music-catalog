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
