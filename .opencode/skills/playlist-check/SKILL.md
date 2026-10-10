---
name: Playlist Check
description: Check a YouTube playlist for new tracks, consult the user on artist attribution, propose a companion representative track with YouTube/Spotify search links, import approvals, and commit the data repo.
---

# Playlist Check — YouTube playlist → catalog consultation

Use this when the user says a track was added to a YouTube playlist,
says "check the playlist", or otherwise wants new playlist entries
triaged into the music catalog.

Code repo (this checkout): code + docs + tests only.
Data repo (sibling `../music-catalog-masu`, branch `develop`):
all state under `state/` (`catalog.json`, `review.json`, `snapshots/`).
Never write state files here; never commit secrets.

CLI (from this repo root):

```bash
PYTHONPATH=src python3 -m music_catalog.cli --help
# or, if installed: catalog --help
bash scripts/sync-data.sh status  # pull / push for the data repo
```

## 0. Setup (every run)

1. If the user did not give a playlist URL **or** an export JSON file,
   ask which one they mean. Do not guess URLs.
2. `bash scripts/sync-data.sh pull` (or confirm the data checkout is
   on `develop` and up to date). Resolve the data dir the same way
   the CLI does: `$MUSIC_CATALOG_DATA_DIR`, else sibling
   `../music-catalog-masu`.
3. The static Spotify source is `<data-dir>/playlist.json`, which must
   contain **only** the `MultiGenreByPairs` playlist — every track in
   it is one author's representative track (target: 2 per author).
   If other playlists got in there, reset the file to
   `{"playlists": [<MultiGenreByPairs only>], ...}` and verify counts
   before continuing.
4. Work read-only until step 5. No `--apply`, no state writes,
   no data-repo commits before the user approves each addition.

## 1. Check for new entries (read-only)

- Preferred: fresh flat export (needs `yt-dlp`; if missing, ask the
  user to supply the file or install it):
  `yt-dlp --flat-playlist -J "<playlist-url>" > /tmp/yt-<YYYYMMDD>.json`
- Then diff without writing state (snapshot is the only write, and
  `monitor` always writes one — that is expected):
  ```bash
  PYTHONPATH=src python3 -m music_catalog.cli xref /tmp/yt-<date>.json --compact
  # or, to also leave a timestamped snapshot in state/snapshots/:
  PYTHONPATH=src python3 -m music_catalog.cli monitor youtube /tmp/yt-<date>.json --compact
  ```
- Re-run **without** `--compact` and keep per-item `details`.
  New work is any item with verdict `new`, `fuzzy`
  (xref) / `new_artist`, `known_artist_new_track`, `unknown`
  (monitor). `matched_exact`/`known_track` = already covered.
- If there is nothing new, say so and stop. Do not commit.

Field notes (learned 2026-10-10): most real playlist titles do NOT
parse verbatim (no `Artist - Title` separator, colon without leading
space, leading pipes) — expect curated `Artist - Title` attribution
entries for unknowns, with the user's attribution as authority. For
ambiguous titles (track name as video title, empty titles), fetch the
video description (`yt-dlp --print "%(title)s || %(channel)s ||
%(description)s"`) before attributing — it often names the real
track/artist (and exposes covers: Seren Saraç's entry is a Barış Manço
song). Save the fresh flat export to the data repo as
`extra/youtube-<name>-<PLID>-<YYYYMMDD>.json` (dated; never overwrite
the previous dump).

## 2. Prepare one consultation per new entry

For each new item, collect and show the user:

- `yt_artist`, `yt_title`, watch URL (`https://www.youtube.com/watch?v=<id>`),
  `channel`, and the raw `video_title` when the parse looks lossy.
- Multi-artist splits: `youtube.py` turns `A & B / A, B / A x B - T`
  into one item with several artists. Ask which artist(s) the track
  should represent — one, the other, or both (both = one import
  credits the primary and aliases the rest; a second import for the
  other side is a separate user decision).
- `unknown` (unparsed title, no ` - ` separator, non-Topic channel):
  show `title`/`channel`/`reason` from `artist review` and ask the
  user to attribute or dismiss it manually. Never silently merge.

Ask exactly: "For which catalog author should this be the
representative track?" — one question per entry, in playlist order.

## 3. Artist status + confirmation (per entry)

Before asking to add, run and report (all read-only):

```bash
PYTHONPATH=src python3 -m music_catalog.cli artist list --sort tracks
PYTHONPATH=src python3 -m music_catalog.cli artist review
PYTHONPATH=src python3 -m music_catalog.cli gaps --compact
```

Tell the user, per candidate artist:

- Already in the registry? Exact/alias hit (name + id) or genuinely
  new? If `fuzzy` listed candidates, show them and require an
  explicit choice: keep separate, or later
  `artist merge --keep <id> --drop <id>` / `artist dismiss <id1> <id2>`
  (merges are user-approved only — never auto-merge).
- How many representative tracks they already have (cap 5, soft
  target 2), with titles + sources. Artists over target because they
  host others' representative tracks are normal — say so when true.
- At cap 5: warn the weakest (lowest popularity) track is evicted on
  import, and name it.
- **Shared-representative soft rule** (not hard, user may override):
  avoid crediting the same recording as representative for multiple
  authors. For each candidate track, check before asking to add:
  1. Is this `track_id` already in the catalog under a *different*
     `artist_id`? Then that recording already represents someone
     else — say who, and ask whether to keep the single credit or
     add a distinct version/recording instead.
  2. Does the same (or near-same) title already exist in the catalog
     under another artist? Search `state/catalog.json` tracks by
     normalized title — collabs often appear as separate uploads.
     Flag likely duplicate recordings.
  3. Are any featured/collab artists (`A feat. B`, `A & B`, `A x B`)
     themselves catalog authors? A track credited to X does **not**
     fill Y's representative slots, so adding X's track can leave
     Y short (or change what Y's set should be). Ask explicitly who
     gets the credit; crediting both needs distinct catalog entries
     and explicit user approval per side.
  A genuine joint anthem may still represent both sides — but only as
  an explicit user decision, never by accident.
- **Alias-tangle check:** a "new" name may already exist as an alias
  (`Jay Smith` → alias of Smash Into Pieces) or as an empty Spotify
  record (same Spotify id). Import under the parsed name, then finish
  with an explicit `artist merge --keep <spotify-id> --drop <youtube-id>`
  so tracks land on the canonical record. State the merge plainly when
  asking, so approval covers it.
- **Spotify-availability test** for obscure acts/DJ sets: if neither
  the playlist track nor any candidate companion is on Spotify, say so
  and let the user decide (abandon sets vs YouTube-only credit).
  One-hit wonders may have exactly one other original on vinyl only
  (Energy 52's `Weak`, 1993) — present the Spotify-backed remix vs the
  YouTube-only original as an explicit choice.
- Then ask: add this track for this artist? Yes / no / different
  artist. Respect a no — skip to step 5 with the rest. Park refused or
  deferred non-tracks in a dated todo file with full details
  (`extra/youtube-todo-<YYYYMMDD>.md`: video id, title, channel, URL,
  reason) for the data commit — never silently dropped.

## 4. Propose a companion track (per approved entry)

For each approved addition, propose **one** more representative track
by the same artist, preferably from a **different album** than the
new entry:

- No downloading, no link verification needed. Just give two
  clickable search links the user can open themselves, e.g.
  `https://www.youtube.com/results?search_query=<artist>+<title>`
  and `https://open.spotify.com/search/<artist>%20<title>`.
- Show: title, album (if known), why it complements (different
  album/era/style), plus both search links. Ask: include it alongside
  the playlist track? Yes/no. The user handles the rest (picks the
  exact video/track and supplies the URL or export snippet for step 5).
- If the artist already has ≥ 2 tracks after the playlist addition,
  say so and still offer the companion as an optional upgrade —
  the user decides.

## 5. Apply the approved additions

- Build ONE filtered file with only approved playlist entries —
  copy the original entry dicts verbatim from the export:
  `{"entries": [<approved entry dicts...>]}` → `/tmp/yt-approved.json`.
  Never `--apply` the full playlist file.
- Hand-picked companion tracks (not in the playlist) go in a second
  file in export shape, e.g. Spotify shape:
  `{"tracks": [{"track": {"id": "spotify:<id>", "name": "<title>", "artists": [{"id": "local:<slug>", "name": "<Artist>"}], "album": {"name": "<album>"}, "external_urls": {"spotify": "<url>"}, "popularity": 0}}]}`
  (YouTube shape `{"entries": [{"id": "<videoid>", "title": "<Artist> - <title>", ...}]}` also works.)
- Preview, then apply:
  ```bash
  PYTHONPATH=src python3 -m music_catalog.cli import /tmp/yt-approved.json --source youtube --dry-run
  PYTHONPATH=src python3 -m music_catalog.cli import /tmp/yt-approved.json --source youtube
  # companions, if any:
  PYTHONPATH=src python3 -m music_catalog.cli import /tmp/companions.json --source spotify --dry-run
  PYTHONPATH=src python3 -m music_catalog.cli import /tmp/companions.json --source spotify
  ```
  (Note: `--dry-run` dedups by id and enforces the cap, but does not
  flag shared-representative credit — that check lives in step 3.)
  The dry-run must show `unknowns: 0` for curated attributions; any
  leftover unknown means the `Artist - Title` form didn't parse —
  fix the separator before applying. Companion videos found outside
  the playlist go in the curated file in YouTube-shape
  (`{"entries": [{"id", "title": "Artist - Track", "channel", ...}]}`);
  resolve their ids with `yt-dlp "ytsearchN:<artist title>"` and
  eyeball title/channel rather than inventing links. Multi-artist
  video titles credit the primary only — unrecorded collaborators stay
  invisible unless the user asks for aliases. One `track_id` can only
  ever represent one author (global dedup): crediting a shared
  recording to EVO today means satirin/FUNK DEMON can't re-add the
  same video tomorrow — say this out loud when splitting collabs.
- Summarize the reports (`added_artists / added_tracks /
  duplicate_tracks / capped_tracks / unknowns / pending_merges`).
  Route leftovers: `unknown` → review queue, `fuzzy`/`pending_merges`
  → `artist review` + explicit merge/dismiss in a follow-up.

## 6. Commit the data repo

1. `git -C <data-dir> status --short` — expect `state/catalog.json`,
   `state/review.json`, and new `state/snapshots/*.json` only.
2. `git -C <data-dir> add state/catalog.json state/review.json state/snapshots/`
   (nothing else; never `code/`, never secrets).
3. `git -C <data-dir> commit -m "playlist-check: <artist> — <track>[, ...] (<YYYY-MM-DD>)"`.
4. Show the commit and `bash scripts/sync-data.sh status`. Ask before
   `bash scripts/sync-data.sh push` (push needs user approval per
   `opencode.jsonc`). If the viz is stale
   (`catalog viz --out-dir <data-dir>/docs --check` exits 1), offer
   `bash scripts/publish-viz.sh` as a follow-up commit.
5. Conclude with the addition list: artist → track(s) + listen
   link(s), and the data-repo commit hash.
