"""D03-D05: detectors, incident merging, evaluation, label guard and the one-time report rule.

All tests use small synthetic KPI tables; no database needed.
"""

import ast
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from payment_reliability import cli
from payment_reliability.detectors import build_series, detect, pooled, robust_z
from payment_reliability.evaluation import evaluate, right_target
from payment_reliability.incidents import merge_incidents

PKG = Path(__file__).resolve().parents[1] / "payment_reliability"
CONFIG = Path(__file__).resolve().parents[1] / "configs" / "detector.yaml"
T0 = pd.Timestamp("2026-01-05T00:00:00Z")
PARAMS = {
    "baseline_buckets": 96,
    "min_history_buckets": 48,
    "robust_z": {"threshold": 7.0},
    "pooled": {"pool_buckets": 2, "threshold": 8.0},
}


def make_kpis(
    n_buckets: int = 300, attempts: int = 40, fail_p: float = 0.1, step: tuple[int, int] = (0, 0),
    step_p: float = 0.1, seed: int = 0,
) -> dict[str, pd.DataFrame]:  # fmt: skip
    """KPI tables shaped like `make kpi` output: one provider plus ALL, two methods."""
    rng = np.random.default_rng(seed)
    buckets = T0 + pd.to_timedelta(np.arange(n_buckets) * 15, unit="min")
    p = np.full(n_buckets, fail_p)
    p[step[0] : step[1]] = step_p
    fails = rng.binomial(attempts, p)
    lat = np.exp(rng.normal(np.log(500), 0.05, n_buckets))
    prov = pd.DataFrame(
        {
            "bucket_start": buckets,
            "provider_id": "prov_a",
            "attempts": attempts,
            "technical_failures": fails,
            "latency_attempts": attempts,
            "latency_p50_ms": lat,
        }
    )
    prov["technical_failure_rate"] = prov["technical_failures"] / attempts
    prov = pd.concat([prov, prov.assign(provider_id="ALL")], ignore_index=True)
    qr = rng.binomial(attempts, 0.5, n_buckets)
    method = pd.concat(
        [
            pd.DataFrame({"bucket_start": buckets, "payment_method": "QR", "first_attempts": qr,
                          "all_first_attempts": attempts}),
            pd.DataFrame({"bucket_start": buckets, "payment_method": "CARD",
                          "first_attempts": attempts - qr, "all_first_attempts": attempts}),
        ],
        ignore_index=True,
    )  # fmt: skip
    method["method_share"] = method["first_attempts"] / attempts
    return {"provider_15m": prov, "method_15m": method, "errors_15m": pd.DataFrame()}


def _failure_series(kpis: dict[str, pd.DataFrame], target: str = "prov_a") -> Any:
    return next(
        s for s in build_series(kpis) if s.target == target and s.metric == "technical_failure_rate"
    )


# --- D03 detectors ---


def test_pooled_finds_a_known_step_and_stays_quiet_elsewhere() -> None:
    kpis = make_kpis(step=(200, 206), step_p=0.45)
    score = pooled(_failure_series(kpis), 96, 48, 2)
    assert np.nanmax(score[200:207]) > 8
    quiet = np.r_[score[:200], score[210:]]
    assert np.nanmax(quiet) < 5


def test_robust_z_also_finds_a_large_step() -> None:
    score = robust_z(_failure_series(make_kpis(step=(200, 206), step_p=0.6)), 96, 48)
    assert np.nanmax(score[200:206]) > 7


def test_pooled_score_shrinks_with_fewer_attempts() -> None:
    """Same rate change, fewer attempts -> weaker evidence (the point of D-B)."""
    big = pooled(_failure_series(make_kpis(attempts=40, step=(200, 206), step_p=0.3)), 96, 48, 2)
    small = pooled(_failure_series(make_kpis(attempts=5, step=(200, 206), step_p=0.3)), 96, 48, 2)
    assert np.nanmax(small[200:207]) < np.nanmax(big[200:207])


def test_no_score_without_enough_history() -> None:
    score = pooled(_failure_series(make_kpis()), 96, 48, 2)
    assert np.isnan(score[:97]).all()
    assert np.isnan(robust_z(_failure_series(make_kpis()), 96, 48)[:48]).all()


def test_traffic_drop_raises_the_method_share_score() -> None:
    kpis = make_kpis()
    m = kpis["method_15m"]
    window = (m["payment_method"] == "QR") & m.index.isin(range(200, 206))
    m.loc[window, "first_attempts"] = 4  # QR share falls from about 0.5 to 0.1
    share = next(s for s in build_series(kpis) if s.target == "QR")
    assert share.direction == -1
    # hand check: 2 buckets x 40 new payments, expected 40 QR, seen 8 -> (40 - 8) / sqrt(20) = 7.2
    np.testing.assert_allclose(np.nanmax(pooled(share, 96, 48, 2)[200:207]), 7.2, atol=0.3)


def test_detect_returns_every_series_for_both_detectors() -> None:
    out = detect(make_kpis(), PARAMS)
    assert set(out["detector"]) == {"robust_z", "pooled"}
    # 2 targets x 2 provider metrics + 2 methods = 6 series, 300 buckets each, 2 detectors
    assert len(out) == 6 * 300 * 2
    assert out["alert"].dtype == bool


# --- label guard (detector must not see ground truth) ---


@pytest.mark.parametrize("module", ["detectors.py", "incidents.py", "kpi.py"])
def test_detection_code_cannot_reach_labels(module: str) -> None:
    source = (PKG / module).read_text("utf-8")
    assert "anomaly_labels" not in source
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in (node.names if isinstance(node, ast.Import) else [node])
    }
    assert not any("evaluation" in (name or "") for name in imported)


def test_labels_do_not_change_alerts_or_incidents() -> None:
    cfg = yaml.safe_load(CONFIG.read_text("utf-8"))
    kpis = make_kpis(step=(200, 206), step_p=0.45)
    fake = [{"anomaly_id": "anom-01", "type": "provider_outage", "start": "2026-01-07T02:00:00Z",
             "end": "2026-01-07T03:00:00Z", "magnitude": 4, "provider_id": "prov_a",
             "payment_method": None, "error_code": None}]  # fmt: skip
    a1, i1, _ = cli.score_and_evaluate(cfg, kpis, [])
    a2, i2, _ = cli.score_and_evaluate(cfg, kpis, fake)
    pd.testing.assert_frame_equal(a1, a2)
    assert i1 == i2


# --- D04 incidents ---


def _alerts(rows: list[tuple[str, str, int]]) -> pd.DataFrame:
    """(target, metric, bucket number) of alerted buckets."""
    return pd.DataFrame(
        {
            "detector": "pooled",
            "target_type": "provider",
            "target": [r[0] for r in rows],
            "metric": [r[1] for r in rows],
            "bucket_start": [T0 + pd.Timedelta(minutes=15 * r[2]) for r in rows],
            "score": 9.0,
            "alert": True,
        }
    )


def test_incidents_merge_small_gaps_and_split_large_ones() -> None:
    rate, lat = "technical_failure_rate", "latency_p50"
    rows = [("a", rate, 0), ("a", lat, 1), ("a", rate, 3), ("a", rate, 6), ("b", rate, 1)]
    inc = merge_incidents(_alerts(rows), max_gap_buckets=1)
    a = [i for i in inc if i["target"] == "a"]
    assert [(i["start"], i["end"], i["buckets"]) for i in a] == [
        ("2026-01-05T00:00:00Z", "2026-01-05T01:00:00Z", 4),  # buckets 0-3, gap of 1 merged
        ("2026-01-05T01:30:00Z", "2026-01-05T01:45:00Z", 1),  # bucket 6, gap of 2 split
    ]
    assert a[0]["metrics"] == [lat, rate]
    assert a[0]["first_alert_at"] == "2026-01-05T00:15:00Z"  # end of the first alerted bucket
    assert [i["target"] for i in inc if i["target"] == "b"] == ["b"]
    assert sorted(i["incident_id"] for i in inc) == ["pooled-001", "pooled-002", "pooled-003"]


# --- D05 evaluation (hand-computed case) ---


def _inc(iid: str, target: str, start: str, end: str, first: str, ttype: str = "provider") -> dict:
    return {"incident_id": iid, "target_type": ttype, "target": target, "start": start,
            "end": end, "first_alert_at": first}  # fmt: skip


def test_evaluation_matches_a_hand_computed_case() -> None:
    labels = [
        {"anomaly_id": "anom-01", "type": "provider_outage", "start": "2026-01-05T10:00:00.000Z",
         "end": "2026-01-05T11:00:00.000Z", "magnitude": 4, "provider_id": "prov_a",
         "payment_method": None, "error_code": None},
        {"anomaly_id": "anom-02", "type": "traffic_drop", "start": "2026-01-05T14:00:00.000Z",
         "end": "2026-01-05T15:00:00.000Z", "magnitude": 5, "provider_id": None,
         "payment_method": "QR", "error_code": None},
    ]  # fmt: skip
    d = "2026-01-05T"
    incidents = [
        _inc("x-1", "prov_a", d + "10:15:00Z", d + "10:45:00Z", d + "10:30:00Z"),
        _inc("x-2", "ALL", d + "10:15:00Z", d + "10:30:00Z", d + "10:30:00Z"),
        _inc("x-3", "prov_a", d + "20:00:00Z", d + "20:15:00Z", d + "20:15:00Z"),
        # starts in the 15-minute grace period after anom-02 ends, wrong kind of target
        _inc("x-4", "prov_a", d + "15:05:00Z", d + "15:30:00Z", d + "15:20:00Z"),
    ]  # fmt: skip
    ev = evaluate(incidents, labels, days=2.0, grace_minutes=15)
    first, second = ev["anomalies"]
    assert first["detected"] and first["delay_minutes"] == 30 and first["incidents"] == ["x-1"]
    assert not second["detected"] and second["detected_any_target"]
    assert ev["detected"] == 1 and ev["detected_any_target"] == 2
    assert ev["false_incidents"] == 1 and ev["false_incident_ids"] == ["x-3"]
    assert ev["false_per_day"] == 0.5
    assert ev["wrong_target_incidents"] == 2  # x-2 (ALL for a provider outage) and x-4


def test_error_burst_on_all_providers_accepts_any_provider_target() -> None:
    lab = {"type": "error_burst", "provider_id": None, "payment_method": None}
    assert right_target({"target_type": "provider", "target": "ALL"}, lab)
    assert right_target({"target_type": "provider", "target": "prov_b"}, lab)
    assert not right_target({"target_type": "method", "target": "QR"}, lab)


# --- D05 tuning / report rules ---


def _workspace(tmp_path: Path, status: str = "draft") -> tuple[dict[str, Any], Path]:
    cfg = yaml.safe_load(CONFIG.read_text("utf-8"))
    cfg["status"] = status
    root = tmp_path / "artifacts"
    for purpose, seed in (("tuning", 0), ("report", 1)):
        sid = cfg["simulations"][purpose]
        sim = root / "simulations" / sid
        sim.mkdir(parents=True)
        (sim / "simulation_manifest.yaml").write_text(
            yaml.safe_dump({"config": {"purpose": purpose}})
        )
        (sim / "anomaly_labels.json").write_text("[]")
        kdir = root / "kpi" / sid
        kdir.mkdir(parents=True)
        for name, frame in make_kpis(seed=seed).items():
            frame.to_parquet(kdir / f"{name}.parquet", index=False)
        (kdir / "kpi_manifest.json").write_text("{}")
    return cfg, root


def test_detect_runs_on_tuning_and_writes_the_run_folder(tmp_path: Path) -> None:
    cfg, root = _workspace(tmp_path)
    out = cli.cmd_detect(cfg, root / "kpi", root / "simulations", root)
    names = {p.name for p in out.iterdir()}
    assert {"config.yaml", "scores.parquet", "incidents.json", "evaluation.json",
            "git_sha.txt", "environment.txt"} <= names  # fmt: skip
    again = cli.cmd_detect(cfg, root / "kpi", root / "simulations", root)
    assert (out / "evaluation.json").read_bytes() == (again / "evaluation.json").read_bytes()


def test_detect_refuses_a_report_simulation(tmp_path: Path) -> None:
    cfg, root = _workspace(tmp_path)
    cfg["simulations"]["tuning"] = cfg["simulations"]["report"]
    with pytest.raises(cli.DetectError, match="not a tuning simulation"):
        cli.cmd_detect(cfg, root / "kpi", root / "simulations", root)


def test_detect_report_refuses_a_draft_config(tmp_path: Path) -> None:
    cfg, root = _workspace(tmp_path, status="draft")
    with pytest.raises(cli.DetectError, match="frozen"):
        cli.cmd_detect_report(cfg, root / "kpi", root / "simulations", root, force=False)


def test_detect_report_runs_once_unless_forced(tmp_path: Path) -> None:
    cfg, root = _workspace(tmp_path, status="frozen")
    args = (cfg, root / "kpi", root / "simulations", root)
    out = cli.cmd_detect_report(*args, force=False)
    assert json.loads((out / "evaluation.json").read_text())["stage"] == "report"
    with pytest.raises(cli.DetectError, match="already evaluated"):
        cli.cmd_detect_report(*args, force=False)
    forced = cli.cmd_detect_report(*args, force=True)
    assert "warning" in json.loads((forced / "evaluation.json").read_text())
    assert len(json.loads((root / "detect_report_runs.json").read_text())) == 2


def test_each_detection_run_records_an_execution(tmp_path: Path) -> None:
    """ADR 0010: run_id stays the hash key; each execution adds executions/<execution_id>.json."""
    cfg, root = _workspace(tmp_path, status="frozen")
    out = cli.cmd_detect(cfg, root / "kpi", root / "simulations", root)
    records = [json.loads(p.read_text()) for p in (out / "executions").glob("exec-*.json")]
    assert len(records) == 1 and records[0]["experiment_id"] == out.name
    assert "evaluation.json" in records[0]["files"]
    report = cli.cmd_detect_report(cfg, root / "kpi", root / "simulations", root, force=False)
    entry = json.loads((root / "detect_report_runs.json").read_text())[-1]
    assert (report / "executions" / f"{entry['execution_id']}.json").is_file()


def test_run_hash_ignores_status_only() -> None:
    cfg = yaml.safe_load(CONFIG.read_text("utf-8"))
    frozen = {**cfg, "status": "frozen"}
    assert cli.run_hash(cfg, "sim-a") == cli.run_hash(frozen, "sim-a")
    assert cli.run_hash(cfg, "sim-a") != cli.run_hash(cfg, "sim-b")
    changed = {**cfg, "incidents": {"max_gap_buckets": 2}}
    assert cli.run_hash(changed, "sim-a") != cli.run_hash(cfg, "sim-a")


def test_tune_ranks_feasible_settings_first() -> None:
    cfg = yaml.safe_load(CONFIG.read_text("utf-8"))
    labels = [{"anomaly_id": "anom-01", "type": "provider_outage",
               "start": "2026-01-07T02:00:00.000Z", "end": "2026-01-07T03:30:00.000Z",
               "magnitude": 4, "provider_id": "prov_a", "payment_method": None,
               "error_code": None}]  # fmt: skip
    grid = cli.tune(cfg, make_kpis(step=(200, 206), step_p=0.45), labels)
    best = grid[grid["detector"] == "pooled"].iloc[0]
    assert best["feasible"] and best["detected"] == 1


def test_plot_of_a_run_is_written(tmp_path: Path) -> None:
    from payment_reliability.plots import plot_run

    cfg, root = _workspace(tmp_path)
    sid = cfg["simulations"]["tuning"]
    label = {"anomaly_id": "anom-01", "type": "provider_outage",
             "start": "2026-01-07T02:00:00.000Z", "end": "2026-01-07T03:30:00.000Z",
             "magnitude": 4, "provider_id": "prov_a", "payment_method": None,
             "error_code": None}  # fmt: skip
    (root / "simulations" / sid / "anomaly_labels.json").write_text(json.dumps([label]))
    run = cli.cmd_detect(cfg, root / "kpi", root / "simulations", root)
    out = plot_run(run, root / "kpi", root / "simulations", tmp_path / "chart.png")
    assert out.stat().st_size > 0
