"""Stage F dashboard: builds from run folders, says clearly what is missing, reads no dataset."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dashboard.build import build, find_detection_run, main, provider_summary, vn

T0 = pd.Timestamp("2026-01-05T00:00:00Z")


def _provider_kpis(n: int = 96 * 2) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    frames = []
    for provider in ("prov_001", "prov_002", "ALL"):
        attempts = rng.integers(20, 40, n)
        frames.append(
            pd.DataFrame(
                {
                    "bucket_start": T0 + pd.to_timedelta(np.arange(n) * 15, unit="min"),
                    "provider_id": provider,
                    "attempts": attempts,
                    "successes": (attempts * 0.8).astype(int),
                    "first_attempts": attempts - 3,
                    "first_attempt_successes": (attempts * 0.7).astype(int),
                    "retries": 3,
                    "technical_failures": (attempts * 0.15).astype(int),
                    "business_failures": (attempts * 0.05).astype(int),
                    "latency_attempts": attempts,
                    "latency_p50_ms": rng.normal(500, 30, n),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _artifacts(root: Path, with_report: bool = True, with_fraud: bool = False) -> Path:
    sid = "sim-test"
    (root / "kpi" / sid).mkdir(parents=True)
    _provider_kpis().to_parquet(root / "kpi" / sid / "provider_15m.parquet", index=False)
    run = root / "detections" / "det-x" / ("report" if with_report else "")
    run.mkdir(parents=True, exist_ok=True)
    incident = {"incident_id": "pooled-001", "detector": "pooled", "target_type": "provider",
                "target": "prov_002", "metrics": ["technical_failure_rate"],
                "start": "2026-01-05T10:00:00Z", "end": "2026-01-05T11:00:00Z",
                "first_alert_at": "2026-01-05T10:15:00Z", "buckets": 4,
                "max_score": 12.3}  # fmt: skip
    (run / "incidents.json").write_text(json.dumps([incident]))
    anomaly = {"anomaly_id": "anom-01", "type": "provider_outage", "magnitude": 3.0,
               "target": "prov_002", "detected": True, "delay_minutes": 15.0}  # fmt: skip
    evaluation = {"simulation_id": sid, "stage": "report" if with_report else "tuning",
                  "run_id": "det-x", "detectors": {"pooled": {"anomalies": [anomaly], "detected": 1,
                  "total": 1, "false_per_day": 0.0}}}  # fmt: skip
    (run / "evaluation.json").write_text(json.dumps(evaluation))
    if with_fraud:
        part = {"pr_auc": 0.165, "pr_auc_ci": {"low": 0.155, "high": 0.176}, "prevalence": 0.0344,
                "recall_at_fpr": {"recall": 0.28}}  # fmt: skip
        out = root / "runs" / "run-abc" / "test"
        out.mkdir(parents=True)
        (out / "metrics.json").write_text(json.dumps(
            {"run_id": "run-abc", "stage": "final", "models": {"logistic": {"test": part}}}
        ))  # fmt: skip
    return root


def test_vietnamese_numbers() -> None:
    assert vn(29340, 0) == "29.340" and vn(0.165) == "0,165" and vn(None) == "—"


def test_page_has_both_products_and_the_incident(tmp_path: Path) -> None:
    html = build(_artifacts(tmp_path, with_fraud=True))
    assert "Product 01" in html and "Product 02" in html
    assert "pooled-001" in html and "prov_002" in html
    assert "05/01 17:00" in html  # 10:00 UTC shown in Vietnam time
    assert "0,165 [0,155; 0,176]" in html and "<b>Test</b>" in html
    assert html.count("data:image/png;base64,") == 2


def test_missing_runs_are_explained_not_fatal(tmp_path: Path) -> None:
    html = build(tmp_path)
    assert "Chưa có lần chạy detector" in html
    assert "Chưa có lần chạy trong" in html and "Chưa chạy <code>make leakage</code>" in html


def test_report_run_is_preferred_over_tuning(tmp_path: Path) -> None:
    root = _artifacts(tmp_path)
    tuning = root / "detections" / "det-y"
    tuning.mkdir()
    (tuning / "evaluation.json").write_text("{}")
    assert find_detection_run(root).name == "report"


def test_provider_summary_puts_all_last() -> None:
    kpis = _provider_kpis()
    summary = provider_summary(kpis)
    assert list(summary.index) == ["prov_001", "prov_002", "ALL"]
    rows = kpis[kpis["provider_id"] == "prov_001"]
    expected = rows["successes"].sum() / rows["attempts"].sum()
    assert summary.loc["prov_001", "success_rate"] == pytest.approx(expected)


def test_cli_writes_the_page(tmp_path: Path) -> None:
    out = tmp_path / "dash" / "index.html"
    assert main(["--artifacts-dir", str(_artifacts(tmp_path / "a")), "--out", str(out)]) == 0
    assert out.read_text("utf-8").startswith("<!doctype html>")
