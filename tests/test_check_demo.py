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


demo_spec = importlib.util.spec_from_file_location("demo", ROOT / "scripts" / "demo.py")
assert demo_spec and demo_spec.loader
demo = importlib.util.module_from_spec(demo_spec)
demo_spec.loader.exec_module(demo)


def test_demo_stops_early_with_a_how_to_when_postgres_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "database_problem", lambda: "no db: make up")
    ran = []
    monkeypatch.setattr(demo.subprocess, "run", lambda *a, **k: ran.append(a))
    assert demo.main() == 2
    assert "make up" in capsys.readouterr().err and ran == []  # no step started


def test_demo_runs_every_step_and_says_where_output_goes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "database_problem", lambda: None)
    calls = []

    def fake_run(cmd: list[str], **kwargs: object) -> object:
        calls.append(cmd)
        out = '{"rows_read": 5, "rows_accepted": 5, "rows_duplicate": 0, "rows_rejected": 0}'
        return type("P", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    monkeypatch.setattr(demo.subprocess, "run", fake_run)
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert len(calls) == len(demo.STEPS) and f"[{len(demo.STEPS)}/{len(demo.STEPS)}]" in out
    assert "5 dòng mới" in out and "index.html" in out


def test_demo_reports_the_failing_step(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "database_problem", lambda: None)
    result = type("P", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
    monkeypatch.setattr(demo.subprocess, "run", lambda *a, **k: result)
    assert demo.main() == 1
    err = capsys.readouterr().err
    assert "THẤT BẠI" in err and "boom" in err


def test_demo_script_never_touches_the_report_simulation() -> None:
    text = (ROOT / "scripts" / "demo.py").read_text("utf-8")
    assert "sim-f6e6749ff0bf" not in text and "detect-report" not in text
    assert "report.yaml" not in text and demo.SIM == check_demo.SIMULATION
