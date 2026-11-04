"""D01/D02: KPI views match an independent pandas computation; `make kpi` export.

Database tests skip when PostgreSQL is not running.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
import pytest
import yaml
from payment_reliability.kpi import KpiError, export_kpis, fetch_kpis, load_kpis
from synthetic_generator.cli import write_simulation
from synthetic_generator.config import SimulationConfig
from synthetic_generator.ingest import ingest, schema_files

DEMO = (
    Path(__file__).resolve().parents[3] / "shared" / "synthetic-generator" / "configs" / "demo.yaml"
)
TECHNICAL = {"TIMEOUT", "PROVIDER_ERROR", "NETWORK_ERROR"}
BUSINESS = {"DECLINED", "INVALID_REQUEST"}


def _small_sim(tmp_path: Path) -> Path:
    """One day of the demo world with its first anomaly (an outage on 2026-01-06)."""
    raw = yaml.safe_load(DEMO.read_text("utf-8"))
    raw["status"] = "draft"
    raw["time"] = {**raw["time"], "start_date": "2026-01-06", "days": 1}
    raw["anomalies"] = raw["anomalies"][:1]
    return write_simulation(SimulationConfig.model_validate(raw), tmp_path)


def _reference(sim: Path) -> pd.DataFrame:
    """Provider KPIs computed in pandas straight from events.jsonl (non-empty buckets only)."""
    rows = [json.loads(line) for line in (sim / "events.jsonl").read_text("utf-8").splitlines()]
    df = pd.DataFrame([{**r["payload"], "event_time": r["event_time"]} for r in rows])
    df["bucket_start"] = pd.to_datetime(df["event_time"], utc=True).dt.floor("15min")
    both = pd.concat([df, df.assign(provider_id="ALL")])

    def kpis(g: pd.DataFrame) -> pd.Series:
        lat = g.loc[g["error_code"] != "TIMEOUT", "latency_ms"].to_numpy()
        first = g[g["attempt_number"] == 1]
        return pd.Series(
            {
                "attempts": len(g),
                "successes": int((g["status"] == "SUCCESS").sum()),
                "first_attempts": len(first),
                "first_attempt_successes": int((first["status"] == "SUCCESS").sum()),
                "retries": int((g["attempt_number"] > 1).sum()),
                "technical_failures": int(g["error_code"].isin(TECHNICAL).sum()),
                "business_failures": int(g["error_code"].isin(BUSINESS).sum()),
                "timeouts": int((g["error_code"] == "TIMEOUT").sum()),
                "latency_p50_ms": np.percentile(lat, 50) if len(lat) else np.nan,
                "latency_p95_ms": np.percentile(lat, 95) if len(lat) else np.nan,
            }
        )

    out = both.groupby(["bucket_start", "provider_id"]).apply(kpis, include_groups=False)
    return out.reset_index()


def test_schema_files_run_in_number_order() -> None:
    names = [p.name for p in schema_files()]
    assert names[:2] == ["001_payment_events.sql", "002_kpi_views.sql"]


def test_provider_kpis_match_pandas(db: psycopg.Connection, tmp_path: Path) -> None:
    sim = _small_sim(tmp_path)
    sid = ingest(db, sim)["simulation_id"]
    got = fetch_kpis(db, sid)["provider_15m"]
    ref = _reference(sim)

    providers = sorted(ref["provider_id"].unique())
    n_buckets = got["bucket_start"].nunique()
    span = (got["bucket_start"].max() - got["bucket_start"].min()) / pd.Timedelta("15min") + 1
    assert n_buckets == span  # no bucket missing between first and last
    assert len(got) == n_buckets * len(providers)  # zero-filled for every provider and ALL

    merged = got.merge(ref, on=["bucket_start", "provider_id"], how="left", suffixes=("", "_ref"))
    empty = merged["attempts_ref"].isna()
    assert (merged.loc[empty, "attempts"] == 0).all()
    assert merged.loc[empty, "success_rate"].isna().all()
    full = merged[~empty]
    for col in (
        "attempts",
        "successes",
        "first_attempts",
        "first_attempt_successes",
        "retries",
        "technical_failures",
        "business_failures",
        "timeouts",
    ):
        assert (full[col] == full[f"{col}_ref"]).all(), col
    for col in ("latency_p50_ms", "latency_p95_ms"):
        np.testing.assert_allclose(full[col], full[f"{col}_ref"].astype(float), equal_nan=True)
    rate = full["technical_failure_rate"]
    np.testing.assert_allclose(rate, full["technical_failures"] / full["attempts"])
    assert ((full["technical_failures"] + full["business_failures"]) <= full["attempts"]).all()


def test_method_and_error_views(db: psycopg.Connection, tmp_path: Path) -> None:
    sim = _small_sim(tmp_path)
    sid = ingest(db, sim)["simulation_id"]
    kpis = fetch_kpis(db, sid)
    method, provider = kpis["method_15m"], kpis["provider_15m"]
    totals = method.groupby("bucket_start")["first_attempts"].sum()
    all_rows = provider[provider["provider_id"] == "ALL"].set_index("bucket_start")
    assert (totals == all_rows["first_attempts"]).all()  # new payments add up
    shares = method.dropna(subset=["method_share"]).groupby("bucket_start")["method_share"].sum()
    np.testing.assert_allclose(shares, 1.0)
    errors = kpis["errors_15m"]
    by_bucket = errors[errors["provider_id"] == "ALL"].groupby("bucket_start")["failures"].sum()
    failed = all_rows["attempts"] - all_rows["successes"]
    assert (by_bucket == failed.loc[by_bucket.index]).all()


def test_export_is_deterministic_and_loadable(db: psycopg.Connection, tmp_path: Path) -> None:
    sid = ingest(db, _small_sim(tmp_path))["simulation_id"]
    first = export_kpis(db, sid, tmp_path / "a")
    second = export_kpis(db, sid, tmp_path / "b")
    for name in ("provider_15m", "errors_15m", "method_15m"):
        assert (first / f"{name}.parquet").read_bytes() == (second / f"{name}.parquet").read_bytes()
    loaded: dict[str, Any] = load_kpis(tmp_path / "a", sid)
    assert (
        len(loaded["provider_15m"])
        == json.loads((first / "kpi_manifest.json").read_text("utf-8"))["rows"]["provider_15m"]
    )


def test_unknown_simulation_fails_clearly(db: psycopg.Connection) -> None:
    with pytest.raises(KpiError, match="make ingest SIM=sim-missing"):
        fetch_kpis(db, "sim-missing")


def test_missing_kpi_files_fail_clearly(tmp_path: Path) -> None:
    with pytest.raises(KpiError, match="make kpi SIM=sim-x"):
        load_kpis(tmp_path, "sim-x")
