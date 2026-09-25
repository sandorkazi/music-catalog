"""CLI: `catalog <cmd>`. stdlib-first."""
from __future__ import annotations

import argparse
import json
import sys

from .data import resolve_data_dir
from .importer import import_items, parse_export
from .store import load_catalog, load_review, save_json


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
