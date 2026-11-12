"""`make demo` last step: the Product 01 demo must reproduce the published TUNING numbers.

Checks only the tuning simulation (demo.yaml) and the detector run of `make detect`. It never
reads or runs the report simulation: that one is evaluated once (`det-08335c6af086`) and its
numbers are only quoted, never recomputed here.

Exit 0 and a short summary when the run matches, 1 with the differences otherwise.
"""

import argparse
import json
import sys
from pathlib import Path

SIMULATION = "sim-485cacc9c858"  # demo.yaml (Stage C)
DETECTION = "det-3ddc26cff253"  # detector.yaml on the tuning simulation (Stage D)
# Published tuning results (README, stage-d-report.md): detector -> (detected of 4, false/day).
EXPECTED = {"pooled": (3, 0.0), "robust_z": (2, 1.0)}
NAMES = {"pooled": "D-B gộp cửa sổ (chính)", "robust_z": "D-A z-score bền vững"}


def check(artifacts: Path) -> tuple[list[str], list[str]]:
    """(summary lines, problems). No problems means the demo matches the published numbers."""
    problems, lines = [], []
    if not (artifacts / "simulations" / SIMULATION).is_dir():
        problems.append(f"simulation {SIMULATION} not found: make simulate changed its output?")
    path = artifacts / "detections" / DETECTION / "evaluation.json"
    if not path.is_file():
        return lines, [*problems, f"{path.as_posix()} not found: make detect did not run"]
    found = json.loads(path.read_text("utf-8"))
    if found.get("simulation_id") != SIMULATION:
        problems.append(f"{DETECTION} ran on {found.get('simulation_id')}, not {SIMULATION}")
    for det, (detected, per_day) in EXPECTED.items():
        res = found["detectors"][det]
        total = len(res["anomalies"])
        lines.append(
            f"{NAMES[det]}: bắt {res['detected']}/{total} sự cố, "
            f"{res['false_per_day']:g} báo nhầm/ngày (công bố: {detected}/4, {per_day:g})"
        )
        if (res["detected"], float(res["false_per_day"]), total) != (detected, per_day, 4):
            problems.append(f"{det}: {res['detected']}/{total}, {res['false_per_day']}/day")
    return lines, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    lines, problems = check(args.artifacts_dir)
    print(f"Product 01 demo ({SIMULATION}, {DETECTION}, bộ tuning):")
    for line in lines:
        print(f"  {line}")
    for line in problems:
        print(f"MISMATCH: {line}", file=sys.stderr)
    if not problems:
        print("  Khớp số đã công bố cho bộ tuning.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
