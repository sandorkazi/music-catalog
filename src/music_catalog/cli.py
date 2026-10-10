"""CLI: `catalog <cmd>`. stdlib-first."""
from __future__ import annotations

import argparse
import json
import sys

from .data import resolve_data_dir
from .importer import import_items, parse_export
from .sources import SOURCES, get_source, monitor_diff, write_snapshot
from .store import (
    artist_track_count,
    dismiss_merge,
    load_catalog,
    load_review,
    merge_artists,
    save_json,
)


def cmd_import(args) -> int:
    items, raw_count = parse_export(args.file, source=args.source)
    catalog, catalog_path = load_catalog(args.data_dir)
    review, review_path = load_review(args.data_dir)
    # dry-run on deep copies so counts are exact without touching disk
    if args.dry_run:
        import copy

        report = import_items(copy.deepcopy(catalog), copy.deepcopy(review), items, source=args.source)
    else:
        report = import_items(catalog, review, items, source=args.source)
        save_json(catalog_path, catalog)
        save_json(review_path, review)
    report["raw_items"] = raw_count
    report["mode"] = "dry-run" if args.dry_run else "applied"
    report["catalog_path"] = str(catalog_path)
    print(json.dumps(report, indent=2))
    return 0


def cmd_xref(args) -> int:
    """Cross-reference a YouTube playlist export against the catalog (read-only by default)."""
    from .youtube import crossref_items

    items, raw_count = parse_export(args.file, source="youtube")
    catalog, catalog_path = load_catalog(args.data_dir)
    if args.apply:
        review, review_path = load_review(args.data_dir)
        report = import_items(catalog, review, items, source="youtube")
        save_json(catalog_path, catalog)
        save_json(review_path, review)
        report["raw_items"] = raw_count
        report["mode"] = "applied"
        report["catalog_path"] = str(catalog_path)
        print(json.dumps(report, indent=2))
    else:
        report = crossref_items(catalog, items, fuzzy_threshold=args.threshold)
        report["raw_items"] = raw_count
        report["mode"] = "dry-run"
        report["catalog_path"] = str(catalog_path)
        if args.compact:
            report.pop("details", None)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_monitor(args) -> int:
    """Unified monitor: fetch via Source, diff new vs known, snapshot, optional apply."""
    from .youtube import crossref_items

    src = get_source(args.source)
    items, raw_count = src.fetch(args.file)
    catalog, catalog_path = load_catalog(args.data_dir)
    if args.source == "youtube":
        report = crossref_items(catalog, items, fuzzy_threshold=args.threshold)
    else:
        report = monitor_diff(catalog, items)
    report["raw_items"] = raw_count
    report["source"] = args.source
    snap = write_snapshot(args.data_dir, args.source, {k: v for k, v in report.items() if k != "details"})
    report["snapshot"] = str(snap)
    if args.apply:
        review, review_path = load_review(args.data_dir)
        applied = import_items(catalog, review, items, source=args.source)
        save_json(catalog_path, catalog)
        save_json(review_path, review)
        report["applied"] = applied
        report["mode"] = "applied"
    else:
        report["mode"] = "dry-run"
    if args.compact:
        report.pop("details", None)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_publish(args) -> int:
    """v2 entry point, v1 stub: dry-run preview only, refuse real writes."""
    catalog, _ = load_catalog(args.data_dir)
    # curated set: target 2 tracks/artist, highest popularity first
    by_artist: dict[str, list] = {}
    for t in catalog["tracks"]:
        by_artist.setdefault(t.get("artist_id"), []).append(t)
    curated = []
    for tracks in by_artist.values():
        tracks = sorted(tracks, key=lambda t: (t.get("popularity", 0), t.get("id", "")), reverse=True)
        curated.extend(tracks[:2])
    targets = [args.to] if args.to != "both" else ["youtube", "spotify"]
    out: dict = {"mode": "dry-run" if args.dry_run else "applied", "curated_tracks": len(curated), "per_source": {}}
    for name in targets:
        src = get_source(name)
        try:
            out["per_source"][name] = src.publish(curated, dry_run=args.dry_run)
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            print(json.dumps(out, indent=2))
            return 2
    if args.limit is not None:
        out["note"] = f"limit flag reserved for v2 batching (requested {args.limit})"
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_candidates(args) -> int:
    """Rank a candidate pool for a gap artist: popular-but-dissimilar 2-pick (SPEC #8)."""
    import json as _json

    from .candidates import pick_candidates
    from .store import find_artist, find_artist_by_name, normalize_name

    catalog, _ = load_catalog(args.data_dir)
    artist = find_artist(catalog, args.artist) or find_artist_by_name(catalog, args.artist)
    if artist is None:
        print(f"error: unknown artist {args.artist!r}", file=sys.stderr)
        return 2
    existing = [t for t in catalog["tracks"] if t.get("artist_id") == artist["id"]]
    with open(args.pool, encoding="utf-8") as f:
        raw_pool = _json.load(f)
    if isinstance(raw_pool, dict) and "track_id" not in raw_pool:
        items, _ = parse_export(args.pool, source=args.source)
        pool = [
            {"id": it.get("track_id"), "title": it.get("title"),
             "popularity": it.get("popularity", 0), "features": {},
             "artists": [a.get("name", "") for a in it.get("artists", [])]}
            for it in items if not it.get("_unknown")
        ]
        # keep pool entries naming this artist; fall back to the whole pool
        mine = [c for c in pool if normalize_name(artist["name"]) in
                [normalize_name(n) for n in c["artists"]]]
        pool = mine or pool
        for c in pool:
            c.pop("artists", None)
    elif isinstance(raw_pool, list):
        pool = raw_pool
    else:
        pool = [raw_pool]
    report = pick_candidates(existing, pool, k=args.limit)
    out = {"artist": {"id": artist["id"], "name": artist["name"],
                      "owned_tracks": len(existing)},
           "pool": len(pool), **report}
    print(_json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_tags(args) -> int:
    """Curated tags: set/show/review/taxonomy (schema v2, manual curation)."""
    from .store import find_artist_by_name
    from .tags import (coverage, find_artist_tags, load_taxonomy, set_artist_tags,
                       untagged_artists, validate_catalog)

    catalog, catalog_path = load_catalog(args.data_dir)
    if args.tags_cmd == "taxonomy":
        tax = load_taxonomy()
        if args.kind == "subgenres":
            print(json.dumps(tax["subgenres"], indent=2, ensure_ascii=False))
        else:
            print(json.dumps(sorted(tax[args.kind]), indent=2, ensure_ascii=False))
        return 0
    if args.tags_cmd == "review":
        bad = validate_catalog(catalog)
        queue = untagged_artists(catalog)
        limit = args.limit
        print(json.dumps({"coverage": coverage(catalog),
                          "taxonomy_violations": bad,
                          "untagged_shown": len(queue[:limit]),
                          "untagged_total": len(queue),
                          "untagged": queue[:limit]},
                         indent=2, ensure_ascii=False))
        return 0
    artist = next((a for a in catalog["artists"] if a.get("id") == args.artist), None)
    artist = artist or find_artist_by_name(catalog, args.artist)
    if artist is None:
        print(f"error: unknown artist {args.artist!r}", file=sys.stderr)
        return 2
    if args.tags_cmd == "show":
        print(json.dumps(find_artist_tags(catalog, artist["id"]),
                         indent=2, ensure_ascii=False))
        return 0
    # set: replace (or --clear); validates against taxonomy
    try:
        summary = set_artist_tags(catalog, artist["id"], genres=args.genre,
                                  subgenres=args.subgenre,
                                  instruments=args.instrument,
                                  source=args.source, clear=args.clear)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    save_json(catalog_path, catalog)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_viz(args) -> int:
    from pathlib import Path

    from .viz import catalog_fingerprint, render_html, render_site

    catalog, _ = load_catalog(args.data_dir)
    sha = catalog_fingerprint(catalog)
    if args.check:
        if not args.out_dir:
            print("error: --check needs --out-dir <site-dir>", file=sys.stderr)
            return 2
        site = Path(args.out_dir) / "graph.json"
        try:
            meta = json.loads(site.read_text(encoding="utf-8")).get("meta", {})
        except (OSError, ValueError) as e:
            print(json.dumps({"fresh": False, "reason": f"unreadable graph.json: {e}",
                              "site": str(site), "catalog_sha256": sha}))
            return 1
        fresh = meta.get("catalog_sha256") == sha
        print(json.dumps({"fresh": fresh, "catalog_sha256": sha,
                          "site_sha256": meta.get("catalog_sha256"),
                          "generated_at": meta.get("generated_at"),
                          "site": str(site)}))
        return 0 if fresh else 1
    if args.out_dir:
        summary = render_site(catalog, args.out_dir, catalog_sha=sha)
        summary["mode"] = "site"
        print(json.dumps(summary, indent=2))
        return 0
    if not args.out:
        print("error: one of --out or --out-dir is required", file=sys.stderr)
        return 2
    out = render_html(catalog)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(out)
    print(json.dumps({"out": args.out, "artists": len(catalog["artists"]),
                      "tracks": len(catalog["tracks"])}))
    return 0


def cmd_similar(args) -> int:
    from .viz import similar_artists, similar_tracks

    catalog, _ = load_catalog(args.data_dir)
    try:
        rows = similar_artists(catalog, args.id, top=args.top, least=args.least) if args.by == "artist" \
            else similar_tracks(catalog, args.id, top=args.top, least=args.least)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"query": args.id, "by": args.by, "least": args.least, "results": rows},
                     indent=2, ensure_ascii=False))
    return 0


def cmd_artist(args) -> int:
    from .links import track_has_source

    catalog, catalog_path = load_catalog(args.data_dir)
    review, review_path = load_review(args.data_dir)
    if args.artist_cmd == "list":
        rows = [
            {"id": a["id"], "name": a["name"], "aliases": a.get("aliases", []),
             "tracks": artist_track_count(catalog, a["id"])}
            for a in catalog["artists"]
        ]
        if args.source:
            ids = {t["artist_id"] for t in catalog["tracks"]
                   if track_has_source(t, args.source)}
            rows = [r for r in rows if r["id"] in ids]
        rows.sort(key=lambda r: (r["tracks"], r["name"].casefold()), reverse=(args.sort == "tracks"))
        if args.sort == "name":
            rows.sort(key=lambda r: r["name"].casefold())
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif args.artist_cmd == "review":
        print(json.dumps({"pending_merges": review["pending_merges"],
                          "unknown": review["unknown"]}, indent=2, ensure_ascii=False))
    elif args.artist_cmd == "merge":
        summary = merge_artists(catalog, review, args.keep, args.drop)
        save_json(catalog_path, catalog)
        save_json(review_path, review)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif args.artist_cmd == "dismiss":
        ok = dismiss_merge(review, args.id1, args.id2)
        if ok:
            save_json(review_path, review)
        print(json.dumps({"dismissed": ok, "ids": sorted([args.id1, args.id2])}))
    return 0


def cmd_gaps(args) -> int:
    """Gap detection (SPEC #7): artists with < 2 tracks, 0-track / 1-track split."""
    from .links import track_source_names

    catalog, _ = load_catalog(args.data_dir)
    gaps = {"zero": [], "one": []}
    for a in catalog["artists"]:
        n = artist_track_count(catalog, a["id"])
        sources = sorted({s for t in catalog["tracks"] if t.get("artist_id") == a["id"]
                          for s in track_source_names(t)})
        if args.source and args.source not in sources:
            continue
        entry = {"id": a["id"], "name": a["name"], "tracks": n, "sources": sources}
        if n == 0:
            gaps["zero"].append(entry)
        elif n == 1:
            gaps["one"].append(entry)
    key = (lambda e: e["name"].casefold()) if args.sort == "name" else (lambda e: (e["tracks"], e["name"].casefold()))
    gaps["zero"].sort(key=key)
    gaps["one"].sort(key=key)
    print(json.dumps({"zero_track_artists": len(gaps["zero"]), "one_track_artists": len(gaps["one"]),
                      "zero": gaps["zero"] if not args.compact else [],
                      "one": gaps["one"] if not args.compact else []},
                     indent=2, ensure_ascii=False))
    return 0


def cmd_coverage(args) -> int:
    """Dual-source coverage: tracks on both vs missing one side (continuous tracker)."""
    from .links import coverage_report

    catalog, _ = load_catalog(args.data_dir)
    rep = coverage_report(catalog)
    key = (lambda e: e["title"].casefold()) if args.sort == "title" \
        else (lambda e: (e["artist"].casefold(), e["title"].casefold()))
    rep["missing_spotify"] = sorted(rep["missing_spotify"], key=key)
    rep["missing_youtube"] = sorted(rep["missing_youtube"], key=key)
    out = {"tracks": rep["tracks"], "both": rep["both"],
           "spotify_only": rep["spotify_only"], "youtube_only": rep["youtube_only"],
           "other": rep["other"]}
    if args.missing in (None, "spotify"):
        out["missing_spotify"] = [] if args.compact else rep["missing_spotify"]
        out["missing_spotify_count"] = len(rep["missing_spotify"])
    if args.missing in (None, "youtube"):
        out["missing_youtube"] = [] if args.compact else rep["missing_youtube"]
        out["missing_youtube_count"] = len(rep["missing_youtube"])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_consolidate(args) -> int:
    """Merge same-artist same-title duplicates into dual-source tracks.

    Read-only by default; ``--apply`` writes. Near-matches are never
    auto-merged — they land in ``needs_review`` for ``catalog link``.
    """
    from .links import consolidate_catalog

    catalog, catalog_path = load_catalog(args.data_dir)
    if args.apply:
        report = consolidate_catalog(catalog, threshold=args.threshold)
        save_json(catalog_path, catalog)
        report["mode"] = "applied"
    else:
        import copy

        report = consolidate_catalog(copy.deepcopy(catalog), threshold=args.threshold)
        report["mode"] = "dry-run"
    report["catalog_path"] = str(catalog_path)
    if args.compact:
        report.pop("pairs", None)
        report.pop("needs_review", None)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_link(args) -> int:
    """Manually attach a missing source ref to a track (fuzzy/review follow-up)."""
    from .links import attach_source, build_ref

    catalog, catalog_path = load_catalog(args.data_dir)
    track = next((t for t in catalog["tracks"] if t.get("id") == args.track), None)
    if track is None and args.by == "title":
        track = next((t for t in catalog["tracks"] if t.get("title", "").casefold() == args.track.casefold()), None)
    if track is None:
        print(f"error: unknown track {args.track!r}", file=sys.stderr)
        return 2
    ext = args.external_id
    if args.source == "youtube" and not ext.startswith("youtube:"):
        ext = f"youtube:{ext}"
    ref = build_ref(args.source, ext, url=args.url,
                    video_title=args.video_title, channel=args.channel)
    if args.dry_run:
        already = args.source in (track.get("sources") or {})
        print(json.dumps({"track": track["id"], "title": track.get("title"),
                          "sources": sorted((track.get("sources") or {})),
                          "would_attach": not already, "mode": "dry-run"}))
        return 0
    attached = attach_source(track, args.source, ref)
    save_json(catalog_path, catalog)
    print(json.dumps({"track": track["id"], "title": track.get("title"),
                      "attached": attached, "sources": sorted(track.get("sources", {})),
                      "mode": "applied"}, indent=2, ensure_ascii=False))
    return 0


def cmd_unlink(args) -> int:
    """Detach a source ref from a track (correction path)."""
    from .links import detach_source

    catalog, catalog_path = load_catalog(args.data_dir)
    track = next((t for t in catalog["tracks"] if t.get("id") == args.track), None)
    if track is None:
        print(f"error: unknown track {args.track!r}", file=sys.stderr)
        return 2
    if not args.apply:
        print(json.dumps({"track": track["id"], "title": track.get("title"),
                          "sources": sorted((track.get("sources") or {})),
                          "would_detach": args.source, "mode": "dry-run"}))
        return 0
    ok = detach_source(track, args.source)
    if ok:
        save_json(catalog_path, catalog)
    print(json.dumps({"track": track["id"], "detached": ok,
                      "sources": sorted((track.get("sources") or {})),
                      "mode": "applied"}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="catalog", description="Music catalog engine (local-first CLI)")
    p.add_argument("--data-dir", default=None, help="override data repo checkout dir")
    sub = p.add_subparsers(dest="cmd", required=True)
    im = sub.add_parser("import", help="import tracks from an export JSON file")
    im.add_argument("file", help="export JSON file (Spotify playlist export or yt-dlp playlist JSON)")
    im.add_argument("--dry-run", action="store_true", help="parse + report without writing state")
    im.add_argument("--source", default="spotify", help="source label for new tracks (spotify|youtube; youtube auto-detected)")
    im.set_defaults(func=cmd_import)
    xr = sub.add_parser("xref", help="cross-reference a YouTube playlist against the artist registry")
    xr.add_argument("file", help="yt-dlp flat-playlist JSON file")
    xr.add_argument("--threshold", type=float, default=0.86, help="fuzzy-match cutoff 0-1 (default 0.86)")
    xr.add_argument("--compact", action="store_true", help="omit per-item details, counts only")
    xr.add_argument("--apply", action="store_true", help="actually import (default is read-only report)")
    xr.set_defaults(func=cmd_xref)
    ar = sub.add_parser("artist", help="artist registry: list/review/merge/dismiss")
    ar_sub = ar.add_subparsers(dest="artist_cmd", required=True)
    ar_l = ar_sub.add_parser("list", help="list artists with track counts")
    ar_l.add_argument("--source", default=None, help="only artists with tracks from this source")
    ar_l.add_argument("--sort", default="name", choices=["name", "tracks"])
    ar_r = ar_sub.add_parser("review", help="show pending merges + unknown queue")
    ar_m = ar_sub.add_parser("merge", help="merge two artists (explicit, user-approved)")
    ar_m.add_argument("--keep", required=True, help="artist id to keep")
    ar_m.add_argument("--drop", required=True, help="artist id to fold in and remove")
    ar_d = ar_sub.add_parser("dismiss", help="reject a pending merge without merging")
    ar_d.add_argument("id1")
    ar_d.add_argument("id2")
    ar.set_defaults(func=cmd_artist)
    gp = sub.add_parser("gaps", help="list artists with < 2 tracks (0-track / 1-track split)")
    gp.add_argument("--source", default=None, help="only artists with tracks from this source")
    gp.add_argument("--sort", default="name", choices=["name", "tracks"])
    gp.add_argument("--compact", action="store_true", help="counts only")
    gp.set_defaults(func=cmd_gaps)
    mo = sub.add_parser("monitor", help="poll a playlist export via a Source (diff + snapshot)")
    mo.add_argument("source", choices=sorted(SOURCES), help="source backend")
    mo.add_argument("file", help="export JSON file (or <memory> for fake)")
    mo.add_argument("--threshold", type=float, default=0.86, help="fuzzy-match cutoff 0-1 (youtube)")
    mo.add_argument("--compact", action="store_true", help="omit per-item details")
    mo.add_argument("--apply", action="store_true", help="import + write state (default is read-only)")
    mo.set_defaults(func=cmd_monitor)
    pu = sub.add_parser("publish", help="publish curated set (v1: --dry-run preview only)")
    pu.add_argument("--to", default="both", choices=["youtube", "spotify", "both"])
    pu.add_argument("--dry-run", action="store_true", help="preview only (required in v1)")
    pu.add_argument("--limit", type=int, default=None, help="v2 batching hint")
    pu.set_defaults(func=cmd_publish)
    ca = sub.add_parser("candidates", help="rank a candidate pool for a gap artist (2-pick)")
    ca.add_argument("artist", help="artist id or name")
    ca.add_argument("--pool", required=True, help="export JSON or track-list JSON file")
    ca.add_argument("--source", default="spotify", help="pool parser hint (spotify|youtube)")
    ca.add_argument("--limit", type=int, default=2, help="how many to pick (default 2)")
    ca.set_defaults(func=cmd_candidates)
    tg = sub.add_parser("tags", help="curated genre/subgenre/instrument tags")
    tg_sub = tg.add_subparsers(dest="tags_cmd", required=True)
    tg_set = tg_sub.add_parser("set", help="replace an artist's tags (validates taxonomy)")
    tg_set.add_argument("artist", help="artist id or name")
    tg_set.add_argument("--genre", action="append", default=[])
    tg_set.add_argument("--subgenre", action="append", default=[])
    tg_set.add_argument("--instrument", action="append", default=[])
    tg_set.add_argument("--source", default="manual")
    tg_set.add_argument("--clear", action="store_true", help="wipe all tags")
    tg_show = tg_sub.add_parser("show", help="show an artist's tags")
    tg_show.add_argument("artist", help="artist id or name")
    tg_rev = tg_sub.add_parser("review", help="coverage + untagged queue + taxonomy violations")
    tg_rev.add_argument("--limit", type=int, default=50)
    tg_tax = tg_sub.add_parser("taxonomy", help="dump the controlled vocabulary")
    tg_tax.add_argument("--kind", default="genres", choices=["genres", "subgenres", "instruments"])
    tg.set_defaults(func=cmd_tags)
    vz = sub.add_parser("viz", help="export static HTML similarity maps (artists+genres, tracks)")
    vz.add_argument("--out", required=False, default=None, help="output HTML file (legacy single-file map)")
    vz.add_argument("--out-dir", required=False, default=None,
                    help="output dir for the github.io browser (graph.json + index.html)")
    vz.add_argument("--check", action="store_true",
                    help="with --out-dir: validate the published graph.json is fresh (exit 1 if stale)")
    vz.set_defaults(func=cmd_viz)
    si = sub.add_parser("similar", help="most/least similar artists or tracks to X")
    si.add_argument("id", help="artist id (with --by artist) or track id (with --by track)")
    si.add_argument("--by", default="artist", choices=["artist", "track"])
    si.add_argument("--top", type=int, default=5)
    si.add_argument("--least", action="store_true", help="flip to least-similar")
    si.set_defaults(func=cmd_similar)
    co = sub.add_parser("coverage", help="dual-source track coverage (both vs missing one side)")
    co.add_argument("--missing", default=None, choices=["spotify", "youtube"],
                    help="show only tracks missing this source (default: both lists)")
    co.add_argument("--sort", default="artist", choices=["artist", "title"])
    co.add_argument("--compact", action="store_true", help="counts only")
    co.set_defaults(func=cmd_coverage)
    cn = sub.add_parser("consolidate", help="merge same-title duplicates into dual-source tracks")
    cn.add_argument("--apply", action="store_true", help="write state (default is read-only dry-run)")
    cn.add_argument("--threshold", type=float, default=0.86,
                    help="fuzzy near-match cutoff for needs_review (default 0.86)")
    cn.add_argument("--compact", action="store_true", help="omit pairs/needs_review details")
    cn.set_defaults(func=cmd_consolidate)
    li = sub.add_parser("link", help="attach a missing source ref to a track")
    li.add_argument("track", help="track id (or title with --by title)")
    li.add_argument("--by", default="id", choices=["id", "title"])
    li.add_argument("--source", required=True, choices=["spotify", "youtube"])
    li.add_argument("--external-id", required=True, help="id on that source (Spotify id / YouTube video id)")
    li.add_argument("--url", default=None)
    li.add_argument("--video-title", default=None)
    li.add_argument("--channel", default=None)
    li.add_argument("--dry-run", action="store_true", help="preview without writing")
    li.set_defaults(func=cmd_link)
    ul = sub.add_parser("unlink", help="detach a source ref from a track")
    ul.add_argument("track", help="track id")
    ul.add_argument("--source", required=True, choices=["spotify", "youtube"])
    ul.add_argument("--apply", action="store_true", help="write state (default is read-only dry-run)")
    ul.set_defaults(func=cmd_unlink)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    # fail fast if data checkout is missing
    try:
        resolve_data_dir(args.data_dir)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
