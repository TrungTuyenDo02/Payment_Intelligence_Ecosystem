"""Copy the small summary files of one run into `results/` so they can be committed (ADR 0010).

Only whitelisted files directly in the run folder (plus `executions/*.json`) are copied: no
dataset, Parquet, model or per-row predictions. Sub-folders such as `test/` are never read.
A test or report folder itself is bundled only with `--owner-test` (the owner's decision;
agents do not read test results). Standard library only.

Usage: python scripts/bundle_results.py artifacts/experiments/cal-04b3ad5944ce
"""

import argparse
import shutil
import sys
from pathlib import Path

FILES = (
    "config.yaml",
    "metrics.json",
    "results.json",
    "evaluation.json",
    "incidents.json",
    "split.json",
    "threshold.json",
    "models.json",
    "summary.md",
    "environment.txt",
    "git_sha.txt",
    "manifest_checksum.txt",
)
MAX_BYTES = 1_000_000
OWNER_ONLY = ("test", "report")


class BundleError(RuntimeError):
    """The folder cannot be bundled (empty, too large, or a test folder without the flag)."""


def selected(run_dir: Path) -> list[Path]:
    """Whitelisted files of `run_dir`, relative paths."""
    files = [Path(name) for name in FILES if (run_dir / name).is_file()]
    executions = run_dir / "executions"
    if executions.is_dir():
        files += [p.relative_to(run_dir) for p in sorted(executions.glob("*.json"))]
    return files


def bundle(run_dir: Path, results_dir: Path, owner_test: bool = False) -> Path:
    """Copy the summary files of `run_dir` to `results_dir/<run id>[/test]`; return that path."""
    run_dir = run_dir.resolve()
    if run_dir.name in OWNER_ONLY and not owner_test:
        raise BundleError(
            f"{run_dir.name}/ holds one-time test or report results: only the owner bundles "
            "it, with --owner-test (make bundle RUN_DIR=... OWNER_TEST=1)"
        )
    files = selected(run_dir)
    if not any(f.parent == Path(".") for f in files):
        raise BundleError(f"{run_dir}: no result files to bundle")
    size = sum((run_dir / f).stat().st_size for f in files)
    if size > MAX_BYTES:
        raise BundleError(
            f"{run_dir}: {size / 1e6:.2f} MB is over the {MAX_BYTES / 1e6:.0f} MB limit"
        )
    name = (
        Path(run_dir.parent.name, run_dir.name)
        if run_dir.name in OWNER_ONLY
        else Path(run_dir.name)
    )
    dest = results_dir / name
    if dest.exists():
        for old in [p for p in dest.rglob("*") if p.is_file()]:
            old.unlink()
    for file in files:
        (dest / file).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run_dir / file, dest / file)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--results-dir", type=Path, default=Path(__file__).resolve().parents[1] / "results"
    )
    parser.add_argument(
        "--owner-test", action="store_true", help="owner only: bundle test/ or report/"
    )
    args = parser.parse_args(argv)
    try:
        print(bundle(args.run_dir, args.results_dir, args.owner_test))
    except BundleError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
