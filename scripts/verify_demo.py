"""`make verify-demo`: check that the run folders the dashboard needs exist (ADR 0010).

Exits non-zero and says what is missing and how to get it, instead of letting
`make dashboard` build a page of empty boxes. Only checks that files exist; reads nothing.
"""

import argparse
import sys
from pathlib import Path

HOW = (
    "run it here (see the README commands) or copy the folder from the owner's machine "
    "(HANDOFF.md); artifacts/ is not in git"
)


def missing(artifacts: Path) -> list[str]:
    """What the dashboard needs and is not there (empty list: ready)."""
    runs = artifacts / "runs"
    problems = []
    if not runs.is_dir():
        problems.append(f"{runs.as_posix()}/ does not exist (Product 02 runs): {HOW}")
    if not any(runs.glob("run-*/metrics.json")):
        problems.append(
            f"no Product 02 run (runs/run-*/metrics.json): make baseline / make gbm; {HOW}"
        )
    if not any((artifacts / "detections").glob("det-*/evaluation.json")):
        problems.append(f"no Product 01 detector run (detections/det-*/): make detect; {HOW}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    problems = missing(args.artifacts_dir)
    for line in problems:
        print(f"missing: {line}", file=sys.stderr)
    if not problems:
        print(f"demo inputs present in {args.artifacts_dir}; run `make dashboard`")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
