"""`make demo` check: the Product 01 demo must reproduce the published tuning numbers."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_demo", ROOT / "scripts" / "check_demo.py")
assert spec and spec.loader
check_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_demo)


def write_run(root: Path, pooled: tuple[int, float], robust: tuple[int, float]) -> Path:
    artifacts = root / "artifacts"
    (artifacts / "simulations" / check_demo.SIMULATION).mkdir(parents=True)
    out = artifacts / "detections" / check_demo.DETECTION
    out.mkdir(parents=True)

    def det(found: int, per_day: float) -> dict:
        anomalies = [{"detected": i < found} for i in range(4)]
        return {"detected": found, "false_per_day": per_day, "anomalies": anomalies}

    body = {
        "simulation_id": check_demo.SIMULATION,
        "detectors": {"pooled": det(*pooled), "robust_z": det(*robust)},
    }
    (out / "evaluation.json").write_text(json.dumps(body), encoding="utf-8")
    return artifacts


def test_published_numbers_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    artifacts = write_run(tmp_path, (3, 0.0), (2, 1.0))
    assert check_demo.main(["--artifacts-dir", str(artifacts)]) == 0
    assert "3/4" in capsys.readouterr().out


def test_different_numbers_fail(tmp_path: Path) -> None:
    artifacts = write_run(tmp_path, (2, 0.0), (2, 1.0))
    lines, problems = check_demo.check(artifacts)
    assert problems == ["pooled: 2/4, 0.0/day"]


def test_missing_run_fails(tmp_path: Path) -> None:
    assert check_demo.main(["--artifacts-dir", str(tmp_path)]) == 1


def test_never_points_at_the_report_simulation() -> None:
    """The demo uses the tuning pair only; the report pair is evaluated once by the owner."""
    text = (ROOT / "scripts" / "check_demo.py").read_text("utf-8")
    assert "sim-f6e6749ff0bf" not in text and "det-08335c6af086" in text  # quoted in a comment
    makefile = (ROOT / "Makefile").read_text("utf-8")
    demo = makefile.split("\ndemo:", 1)[1].split("\n\n", 1)[0]
    assert "report" not in demo and "detect-report" not in demo
