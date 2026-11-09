"""Stage F dashboard: builds from run folders, says clearly what is missing, reads no dataset."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dashboard.build import build, find_detection_run, fold_echoes, main, provider_summary, vn

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


def test_fold_echoes_merges_overlapping_all_incident_only():
    def inc(iid, target, start, end):
        return {"incident_id": iid, "target": target, "start": start, "end": end}

    incidents = [
        inc("pooled-001", "ALL", "2026-01-05T10:15:00Z", "2026-01-05T11:00:00Z"),
        inc("pooled-002", "prov_003", "2026-01-05T10:00:00Z", "2026-01-05T11:30:00Z"),
        inc("pooled-003", "ALL", "2026-01-06T02:00:00Z", "2026-01-06T02:30:00Z"),
        inc("pooled-004", "prov_001", "2026-01-06T02:30:00Z", "2026-01-06T03:00:00Z"),
    ]
    out = fold_echoes(incidents)
    assert [(i["incident_id"], i["echoes"]) for i in out] == [
        ("pooled-002", ["pooled-001"]),
        ("pooled-003", []),  # only touches pooled-004 at 02:30, no overlap
        ("pooled-004", []),
    ]
    assert "echoes" not in incidents[0]  # input left as is


def test_fraud_table_dedupes_labels_variants_and_tolerates_old_runs(tmp_path: Path) -> None:
    def part(ap: float, with_fpr: bool = True) -> dict:
        m = {"pr_auc": ap, "pr_auc_ci": {"low": ap - 0.01, "high": ap + 0.01}, "prevalence": 0.039}
        return {**m, "recall_at_fpr": {"recall": 0.33}} if with_fpr else m

    run = tmp_path / "runs" / "run-old"
    (run / "test").mkdir(parents=True)
    (run / "metrics.json").write_text(json.dumps(
        {"run_id": "run-old", "stage": "validation", "models": {"logistic": {"valid": part(0.245)}}}
    ))  # fmt: skip
    # Made before fpr_target existed: no recall_at_fpr (used to raise KeyError).
    old = {"valid": part(0.245, False), "test": part(0.165, False)}
    (run / "test" / "metrics.json").write_text(
        json.dumps({"run_id": "run-old", "stage": "final", "models": {"logistic": old}})
    )
    hist = tmp_path / "runs" / "run-hist"
    hist.mkdir()
    (hist / "config.yaml").write_text(
        "features:\n  numeric: [a]\n  categorical: [b]\n  derived: [log_amount, card1_prev_count]\n"
    )
    (hist / "metrics.json").write_text(json.dumps(
        {"run_id": "run-hist", "stage": "validation", "models": {"gbm": {"valid": part(0.497)}}}
    ))  # fmt: skip
    leak = tmp_path / "experiments" / "leak-x"
    leak.mkdir(parents=True)
    (leak / "summary.md").write_text(
        "Run `leak-x`\n\n| A | B |\n| --- | --- |\n| `card1` | 0,987 |\n"
    )

    html = build(tmp_path)
    assert html.count("0,245 [") == 1  # validation shown once, not again from the test run
    assert "0,165 [" in html and "4 (+1: card1_*)" in html
    assert ">card1</td>" in html and "| --- |" not in html and "<pre>" not in html


def _diag_results() -> dict:
    def score(pr: float) -> dict:
        return {"pr_auc": pr, "pr_auc_at_common_prevalence": pr, "prevalence": 0.04,
                "recall_at_fpr": 0.33, "rows": 100}  # fmt: skip

    weeks = [
        {"week": w, "rows": 50, "prevalence": 0.03 + w / 1000, "pr_auc": 0.2} for w in range(6)
    ]
    return {
        "matrix": {f"train_{a}__valid_{b}": score(0.2) for a in ("time", "random")
                   for b in ("time", "random")},  # fmt: skip
        "same_rows_in_time_valid_period": {
            "pr_auc_diff_random_minus_time_train": {"diff": 0.01, "low": 0.005, "high": 0.015}},
        "random_valid_without_early_weeks": {"early_weeks": 2, "scores": {"train_time": score(0.21)}},  # noqa: E501
        "weekly_time_valid": weeks[3:], "weekly_random_valid": weeks,
    }  # fmt: skip


def test_new_sections_say_what_is_missing(tmp_path: Path) -> None:
    html = build(_artifacts(tmp_path))
    assert 'id="diag"' in html and 'id="paired"' in html and "<nav>" in html
    assert "split_diagnostics" in html and "paired_comparison" in html  # hints, no crash


def test_diagnostics_and_paired_sections_render(tmp_path: Path) -> None:
    root = _artifacts(tmp_path)
    exp = root / "experiments"
    (exp / "diag-x").mkdir(parents=True)
    (exp / "diag-x" / "results.json").write_text(json.dumps(_diag_results()))
    diff = {"diff": 0.011, "low": 0.005, "high": 0.017}
    cand = {"run-aaa": {"pr_auc_diff": diff, "recall_at_fpr_diff": diff,
                        "pr_auc_diff_clustered": {"diff": 0.01, "low": -0.003, "high": 0.025},
                        "recall_at_fpr_diff_clustered": diff}}  # fmt: skip
    (exp / "paired-x.json").write_text(json.dumps({
        "baseline": "run-base", "validation_rows": 1000, "n_resamples": 50,
        "candidates": cand}))  # fmt: skip
    html = build(root)
    assert "Train theo thời gian" in html and "Validation ngẫu nhiên" in html
    assert "data:image/png;base64" in html and "run-aaa" in html and "run-base" in html
    assert (
        html.count('class="ok"') == 2
    )  # row CI and recall CI exclude 0; the clustered PR-AUC CI does not
