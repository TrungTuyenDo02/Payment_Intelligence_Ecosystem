"""CLI: compute SHA-256 checksums and write a dataset manifest YAML.

Example:
    python -m dataset_management.cli --name ieee-cis \
        --source "Kaggle competition: IEEE-CIS Fraud Detection" \
        --base-dir datasets/raw/ieee-cis --file train_transaction.csv --file train_identity.csv \
        --download-date 2026-10-01 \
        --license-note "Kaggle competition terms, research use only, verify before any other use" \
        --out datasets/manifests/ieee-cis.yaml
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from dataset_management.manifest import DatasetFileNotFoundError, build_manifest, write_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--base-dir", required=True, type=Path)
    parser.add_argument("--file", required=True, action="append", dest="files")
    parser.add_argument(
        "--download-date", required=True, type=date.fromisoformat, help="YYYY-MM-DD (owner)"
    )
    parser.add_argument("--license-note", required=True)
    parser.add_argument("--version", default=None)
    parser.add_argument("--out", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 on success, 2 if a dataset file is missing."""
    args = parse_args(argv)
    try:
        manifest = build_manifest(
            name=args.name,
            source=args.source,
            base_dir=args.base_dir,
            files=args.files,
            license_note=args.license_note,
            download_date=args.download_date,
            version=args.version,
        )
    except DatasetFileNotFoundError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    write_manifest(manifest, args.out)
    print(f"wrote {args.out} (checksum {manifest.checksum})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
