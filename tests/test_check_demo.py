"""`make demo` check: the Product 01 demo must reproduce the published tuning numbers."""

import importlib.util
import json
import sys
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


sys.path.insert(0, str(ROOT / "scripts"))  # demo.py imports check_demo by name
demo_spec = importlib.util.spec_from_file_location("demo", ROOT / "scripts" / "demo.py")
assert demo_spec and demo_spec.loader
demo = importlib.util.module_from_spec(demo_spec)
demo_spec.loader.exec_module(demo)


def fake_products(monkeypatch: pytest.MonkeyPatch, *, db: str | None, data: bool) -> list[str]:
    """Replace the slow parts of demo.main; returns the list of products that ran."""
    ran: list[str] = []
    monkeypatch.setattr(demo, "database_problem", lambda: db)
    monkeypatch.setattr(demo, "DATASET", ROOT / ("pyproject.toml" if data else "missing.csv"))

    def run_product(name: str, steps: list, bar: object) -> dict:
        ran.append(name[:10])
        return {}

    monkeypatch.setattr(demo, "run_product", run_product)
    monkeypatch.setattr(demo, "report_01", lambda out: [(True, "p01 ok")])
    monkeypatch.setattr(demo, "report_02", lambda out: [(True, "p02 ok")])
    return ran


def test_demo_runs_both_products_and_prints_the_checklist(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran = fake_products(monkeypatch, db=None, data=True)
    assert demo.main([]) == 0
    out = capsys.readouterr().out
    assert ran == ["Product 01", "Product 02"]
    assert "✓ p01 ok" in out and "✓ p02 ok" in out and "2/2 kiểm tra đạt" in out


def test_demo_without_postgres_skips_product_01_with_a_how_to(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ran = fake_products(monkeypatch, db="no db: make up", data=True)
    assert demo.main([]) == 2  # a requested product could not run
    captured = capsys.readouterr()
    assert ran == ["Product 02"] and "make up" in captured.err and "Bỏ qua" in captured.out


def test_demo_without_dataset_runs_product_01_only(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = fake_products(monkeypatch, db=None, data=False)
    assert demo.main([]) == 0  # CI: no dataset, Product 02 is optional there
    assert ran == ["Product 01"]
    assert demo.main(["--product", "02"]) == 2  # but asked for explicitly, it is a skip


def test_demo_fails_when_a_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_products(monkeypatch, db=None, data=False)
    monkeypatch.setattr(demo, "report_01", lambda out: [(False, "mismatch")])
    assert demo.main(["--product", "01"]) == 1


def test_demo_step_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(demo, "run_step", lambda args: (False, "boom", 1.0))
    assert demo.run_product("Product 01 — x", demo.STEPS_01, demo.Progress(6)) is None
    err = capsys.readouterr().err
    assert "THẤT BẠI" in err and "boom" in err


def test_product_01_report_reads_the_detection_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    artifacts = write_run(tmp_path, (3, 0.0), (2, 1.0))
    labels = [{"anomaly_id": f"anom-0{i}", "type": "provider_outage", "magnitude": 1.5,
               "provider_id": "prov_001", "payment_method": None, "error_code": None}
              for i in range(4)]  # fmt: skip
    sim = artifacts / "simulations" / check_demo.SIMULATION
    (sim / "anomaly_labels.json").write_text(json.dumps(labels), encoding="utf-8")
    ev_path = artifacts / "detections" / check_demo.DETECTION / "evaluation.json"
    ev = json.loads(ev_path.read_text("utf-8"))
    for det in ev["detectors"].values():
        for i, a in enumerate(det["anomalies"]):
            a.update(anomaly_id=f"anom-0{i}", delay_minutes=15.0 if a["detected"] else None)
    ev_path.write_text(json.dumps(ev), encoding="utf-8")
    monkeypatch.setattr(demo, "ARTIFACTS", artifacts)
    load = '{"rows_read": 9, "rows_accepted": 9, "rows_duplicate": 0, "rows_rejected": 0}'
    checks = demo.report_01({"3": load})
    assert [ok for ok, _ in checks] == [True, True, True, False]  # no dashboard in tmp
    assert "x1,5 (prov_001)" in capsys.readouterr().out


def test_demo_script_never_touches_the_report_simulation() -> None:
    text = (ROOT / "scripts" / "demo.py").read_text("utf-8")
    assert "sim-f6e6749ff0bf" not in text and "detect-report" not in text
    assert "report.yaml" not in text and demo.SIM == check_demo.SIMULATION
