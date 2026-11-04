"""Read the Stage D KPI views of one simulation and store them as Parquet (`make kpi`).

Detectors read these Parquet files, never the database, so they can be tested without PostgreSQL.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

# name -> (view, sort keys). Sorting makes the files identical on every run.
KPI_VIEWS: dict[str, tuple[str, tuple[str, ...]]] = {
    "provider_15m": ("kpi_provider_15m", ("bucket_start", "provider_id")),
    "errors_15m": ("kpi_errors_15m", ("bucket_start", "provider_id", "error_code")),
    "method_15m": ("kpi_method_15m", ("bucket_start", "payment_method")),
}


class KpiError(RuntimeError):
    """The simulation is not loaded or the KPI files are missing."""


def fetch_kpis(conn: psycopg.Connection, simulation_id: str) -> dict[str, pd.DataFrame]:
    """All KPI views of one simulation as DataFrames, sorted by their grain."""
    loaded = conn.execute(
        "SELECT count(*) FROM payment_events WHERE simulation_id = %s", (simulation_id,)
    ).fetchone()[0]
    if loaded == 0:
        raise KpiError(
            f"{simulation_id} is not in payment_events; run `make ingest SIM={simulation_id}` first"
        )
    out = {}
    for name, (view, keys) in KPI_VIEWS.items():
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {view} WHERE simulation_id = %s", (simulation_id,))
            cols = [d.name for d in cur.description]
            frame = pd.DataFrame(cur.fetchall(), columns=cols)
        frame["bucket_start"] = pd.to_datetime(frame["bucket_start"], utc=True)
        out[name] = frame.sort_values(list(keys), kind="stable").reset_index(drop=True)
    return out


def export_kpis(conn: psycopg.Connection, simulation_id: str, out_root: Path) -> Path:
    """Write `<out_root>/<simulation_id>/<name>.parquet` and `kpi_manifest.json`."""
    frames = fetch_kpis(conn, simulation_id)
    out = out_root / simulation_id
    out.mkdir(parents=True, exist_ok=True)
    rows = {}
    for name, frame in frames.items():
        frame.to_parquet(out / f"{name}.parquet", index=False)
        rows[name] = len(frame)
    manifest = {"simulation_id": simulation_id, "rows": rows, "bucket_minutes": 15}
    (out / "kpi_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out


def load_kpis(kpi_root: Path, simulation_id: str) -> dict[str, Any]:
    """KPI DataFrames written by `export_kpis`, keyed by name."""
    folder = kpi_root / simulation_id
    if not (folder / "kpi_manifest.json").exists():
        raise KpiError(f"no KPI files in {folder}; run `make kpi SIM={simulation_id}` first")
    return {name: pd.read_parquet(folder / f"{name}.parquet") for name in KPI_VIEWS}
