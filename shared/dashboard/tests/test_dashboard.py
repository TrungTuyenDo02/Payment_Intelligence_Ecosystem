"""Dashboard: four tabs from run folders, explains what is missing, never reads test results."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dashboard.build import (
    REPO_ROOT,
    build,
    find_detection_run,
    fold_echoes,
    main,
    provider_summary,
    vn,
)
from dashboard.charts import bar_chart, line_chart, nice_ticks

T0 = pd.Timestamp("2026-01-05T00:00:00Z")
SENTINEL = 0.987654  # a test-set number planted where the dashboard must not look


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


def _artifacts(root: Path, stage: str = "tuning") -> Path:
    sid = "sim-test"
    (root / "kpi" / sid).mkdir(parents=True)
    _provider_kpis().to_parquet(root / "kpi" / sid / "provider_15m.parquet", index=False)
    (root / "simulations" / sid).mkdir(parents=True)
    label = {"anomaly_id": "anom-01", "type": "provider_outage", "magnitude": 3.0,
             "provider_id": "prov_002", "payment_method": None, "error_code": None,
             "start": "2026-01-05T10:00:00.000Z", "end": "2026-01-05T11:00:00.000Z"}  # fmt: skip
    (root / "simulations" / sid / "anomaly_labels.json").write_text(json.dumps([label]))
    run = root / "detections" / "det-x" / ("report" if stage == "report" else "")
    run.mkdir(parents=True, exist_ok=True)
    incident = {"incident_id": "pooled-001", "detector": "pooled", "target_type": "provider",
                "target": "prov_002", "metrics": ["technical_failure_rate"],
                "start": "2026-01-05T10:00:00Z", "end": "2026-01-05T11:00:00Z",
                "first_alert_at": "2026-01-05T10:15:00Z", "buckets": 4,
                "max_score": 12.3}  # fmt: skip
    (run / "incidents.json").write_text(json.dumps([incident]))
    anomaly = {"anomaly_id": "anom-01", "type": "provider_outage", "magnitude": 3.0,
               "target": "prov_002", "detected": True, "delay_minutes": 15.0}  # fmt: skip
    det = {"anomalies": [anomaly], "detected": 1, "total": 1, "false_per_day": 0.0}
    evaluation = {"simulation_id": sid, "stage": stage, "run_id": "det-x",
                  "detectors": {"pooled": det, "robust_z": dict(det, detected=0)}}  # fmt: skip
    (run / "evaluation.json").write_text(json.dumps(evaluation))
    return root


def _page(root: Path) -> str:
    return build(root, repo=REPO_ROOT)


def test_vietnamese_numbers() -> None:
    assert vn(29340, 0) == "29.340" and vn(0.165) == "0,165" and vn(None) == "—"


@pytest.mark.parametrize("lo,hi", [(0, 0.497), (0, 0.261), (0, 1340), (0.35, 0.67), (0, 3)])
def test_ticks_cover_the_largest_value(lo: float, hi: float) -> None:
    """Regression: the top tick used to fall below the maximum, so bars ran off the axis."""
    ticks = nice_ticks(lo, hi)
    assert ticks[0] <= lo and ticks[-1] >= hi and len(ticks) >= 2


def test_charts_carry_tooltips_and_direct_labels() -> None:
    svg = line_chart(["a", "b", "c"], [("prov_001", 1, [0.1, None, 0.3])], y_fmt=str,
                     title="t", bands=[(0, 1, "band-alert", "sự cố")])  # fmt: skip
    assert svg.count('class="hover"') == 3 and "prov_001" in svg and "sự cố" in svg
    bars = bar_chart([("x", 2.0, "fill-s1", "tip")], x_fmt=str, title="t", ref=(1.0, "ref"))
    assert 'data-tip="tip"' in bars and "ref" in bars
    assert "Không có dữ liệu" in line_chart([], [], y_fmt=str, title="t")


def test_page_has_four_tabs_both_pipelines_and_the_incident(tmp_path: Path) -> None:
    page = _page(_artifacts(tmp_path))
    for tab in ("overview", "p01", "p02", "quality"):
        assert f'data-tab="{tab}"' in page
    assert "Sinh dữ liệu giả lập" in page and "Chấm điểm theo lô" in page  # both pipelines
    assert "pooled-001" in page and "anom-01" in page and "band-alert" in page
    assert "0,408" in page  # published test number, quoted


def test_missing_runs_are_explained_not_fatal(tmp_path: Path) -> None:
    page = _page(tmp_path)
    assert "make demo" in page and "make score" in page and "chưa có" in page


def test_report_run_is_never_read(tmp_path: Path) -> None:
    """The report simulation was evaluated once; only its published numbers are shown."""
    root = _artifacts(tmp_path, stage="report")
    assert find_detection_run(root) is None
    page = _page(root)
    assert "Chưa có lần chạy detector trên bộ tuning" in page
    assert "det-08335c6af086" in page  # quoted from results/published.json


def test_test_folders_are_never_read(tmp_path: Path) -> None:
    """Sabotage check: a test-set number planted in runs/*/test/ must not reach the page."""
    root = _artifacts(tmp_path)
    run = root / "runs" / "run-abc"
    (run / "test").mkdir(parents=True)
    part = {"pr_auc": SENTINEL, "pr_auc_ci": {"low": SENTINEL, "high": SENTINEL},
            "prevalence": 0.03, "recall_at_fpr": {"recall": SENTINEL}}  # fmt: skip
    (run / "test" / "metrics.json").write_text(json.dumps(
        {"run_id": "run-abc", "stage": "final", "models": {"gbm": {"test": part}}}))  # fmt: skip
    valid = {"pr_auc": 0.4321, "pr_auc_ci": {"low": 0.42, "high": 0.44}, "prevalence": 0.03,
             "recall_at_fpr": {"recall": 0.55}}  # fmt: skip
    (run / "metrics.json").write_text(
        json.dumps(
            {"run_id": "run-abc", "stage": "E", "models": {"gbm": {"valid": valid, "test": part}}}
        )
    )
    page = _page(root)
    assert "0,432" in page  # validation number is shown
    assert vn(SENTINEL) not in page and vn(SENTINEL, 2) not in page


def test_published_numbers_match_the_readme() -> None:
    published = json.loads((REPO_ROOT / "results" / "published.json").read_text("utf-8"))
    readme = (REPO_ROOT / "README.md").read_text("utf-8")
    for m in published["product_02"]["models"]:
        assert vn(m["test_pr_auc"]) in readme
    assert published["product_01"]["report"]["run_id"] in readme


def test_provider_summary_puts_all_last() -> None:
    summary = provider_summary(_provider_kpis(8))
    assert list(summary.index) == ["prov_001", "prov_002", "ALL"]


def test_cli_writes_the_page(tmp_path: Path) -> None:
    out = tmp_path / "out" / "index.html"
    assert main(["--artifacts-dir", str(_artifacts(tmp_path / "a")), "--out", str(out)]) == 0
    assert out.read_text("utf-8").startswith("<!doctype html>")


def test_fold_echoes_merges_overlapping_all_incident_only() -> None:
    def inc(i: str, target: str, start: str, end: str) -> dict:
        return {"incident_id": i, "target": target, "start": start, "end": end}

    incidents = [
        inc("p-1", "prov_002", "2026-01-05T10:00:00Z", "2026-01-05T11:00:00Z"),
        inc("p-2", "ALL", "2026-01-05T10:15:00Z", "2026-01-05T10:45:00Z"),
        inc("p-3", "ALL", "2026-01-06T10:00:00Z", "2026-01-06T10:30:00Z"),
    ]
    out = fold_echoes(incidents)
    assert [o["incident_id"] for o in out] == ["p-1", "p-3"]
    assert out[0]["echoes"] == ["p-2"] and out[1]["echoes"] == []
