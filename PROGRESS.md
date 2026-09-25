# Progress

- [ ] 0 scaffold (`feat/catalog-scaffold`)
- [ ] 1 core store + dedup (`feat/catalog-core`)
- [x] 2 JSON import (`feat/catalog-import`) — `catalog import` + dry-run live, /tmp/playlist.json applied (986 artists / 1472 tracks)
- [ ] 3 YT/Spotify monitors (`feat/catalog-monitors`)
- [ ] 4 gaps + candidates (`feat/catalog-gaps`)
- [ ] 5 visualization (`feat/catalog-viz`)
- [ ] 6 polish + smoke (`feat/catalog-polish`)
- [ ] 7 (v2) publish to YT + Spotify (`feat/catalog-publish`)

Log: last green commit + next box here on every stop.

- 2026-09-25: YT xref for masu set — `src/music_catalog/youtube.py` +
  `catalog xref` (read-only default, `--apply` to write); raw dump in
  data repo `extra/youtube-music-placeholder-PLM_*.json` (103 entries).
  Dry-run vs Spotify catalog: 11 matched_exact / 69 new / 23 unknown.
  `pytest tests/` 8 passed. Applied 2026-09-25: +86 artists / +80 tracks
  (1072 / 1552), 23 unknowns queued, 11 pending merges proposed.
- 2026-09-25: merges done — `catalog artist merge/dismiss/review/list` +
  `catalog gaps` live (`store.merge_artists`, cap-5 + pinned survive).
  Merged 12 (10 YT→Spotify, Ghymes×2, Pain×2), dismissed 1 false positive
  (DVBBS↔Borgeous collab). Now 1060 artists / 1552 tracks, 0 pending,
  23 unknown. Gaps: 65 one-track YT artists, 215 zero + 156 one overall.
  `pytest tests/` 12 passed.
