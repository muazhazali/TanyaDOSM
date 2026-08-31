"""Pre-download all catalogue Parquet files into the local dataset cache.

This ensures the backend can answer questions without an on-demand download
latency hit (or without outbound network access at query time).

Usage:
    uv run python scripts/prefetch_datasets.py [--force-refresh] [--dataset ID]

Exit codes:
    0  all requested datasets cached successfully
    1  one or more datasets could not be downloaded
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from askdosm.catalogue import Catalogue
from askdosm.config import get_settings
from askdosm.data import DatasetCache


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-download even if a fresh cached Parquet already exists.",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        metavar="ID",
        help="Only prefetch the given dataset_id (repeatable). Defaults to all.",
    )
    parser.add_argument(
        "--catalogue",
        type=Path,
        default=None,
        help="Override the catalogue JSON path (defaults to ASKDOSM_CATALOGUE_PATH).",
    )
    args = parser.parse_args()

    config = get_settings()
    catalogue_path = args.catalogue or config.catalogue_path
    catalogue = Catalogue(catalogue_path)

    if args.dataset:
        targets = []
        for dataset_id in args.dataset:
            try:
                targets.append(catalogue.get(dataset_id))
            except ValueError as exc:
                print(f"[error] {exc}", file=sys.stderr)
                return 1
    else:
        targets = catalogue.all()

    cache = DatasetCache(config.cache_dir / "datasets", config.cache_ttl_hours)

    total = len(targets)
    print(f"Prefetching {total} dataset(s) into {cache.directory}")
    failures: list[tuple[str, str]] = []

    for index, definition in enumerate(targets, start=1):
        prefix = f"[{index}/{total}] {definition.dataset_id}"
        existing = cache.path_for(definition.dataset_id)
        if existing.exists() and not args.force_refresh and cache._is_fresh(existing):
            print(f"{prefix} already cached, skipping")
            continue
        try:
            frame = cache.load(definition, force_refresh=args.force_refresh)
            print(f"{prefix} ok ({len(frame)} rows)")
        except Exception as exc:
            failures.append((definition.dataset_id, str(exc)))
            print(f"{prefix} FAILED: {exc}", file=sys.stderr)
            traceback.print_exc()

    print(f"\nDone: {total - len(failures)}/{total} cached")
    if failures:
        print("Failures:")
        for dataset_id, message in failures:
            print(f"  - {dataset_id}: {message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())