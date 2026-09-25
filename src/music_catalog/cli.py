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


def cmd_artist(args) -> int:
    catalog, catalog_path = load_catalog(args.data_dir)
    review, review_path = load_review(args.data_dir)
    if args.artist_cmd == "list":
        rows = [
            {"id": a["id"], "name": a["name"], "aliases": a.get("aliases", []),
             "tracks": artist_track_count(catalog, a["id"])}
            for a in catalog["artists"]
        ]
        if args.source:
            ids = {t["artist_id"] for t in catalog["tracks"] if t.get("source") == args.source}
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
    catalog, _ = load_catalog(args.data_dir)
    gaps = {"zero": [], "one": []}
    for a in catalog["artists"]:
        n = artist_track_count(catalog, a["id"])
        sources = sorted({t.get("source") for t in catalog["tracks"] if t.get("artist_id") == a["id"]})
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
