"""Stage D commands: `make kpi`, `make detect`, `make tune`, `make detect-report`.

- kpi: export the KPI views of one simulation to Parquet (needs PostgreSQL).
- detect: run both detectors on the tuning simulation and evaluate them.
- tune: grid search of thresholds on the tuning simulation only.
- detect-report: one-time evaluation on the report simulation of a config the owner froze.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from payment_reliability.detectors import detect
from payment_reliability.evaluation import evaluate, load_labels
from payment_reliability.incidents import merge_incidents
from payment_reliability.kpi import KpiError, load_kpis

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = REPO_ROOT / "artifacts"
DEFAULT_CONFIG = REPO_ROOT / "projects" / "payment-reliability" / "configs" / "detector.yaml"
DETECTORS = ("robust_z", "pooled")
GRID = {
    "robust_z": {"threshold": [3, 4, 5, 6, 7, 8, 10, 12, 15]},
    "pooled": {"threshold": [3, 4, 5, 6, 7, 8, 10, 12, 15], "pool_buckets": [2, 4, 8]},
}


class DetectError(RuntimeError):
    """A rule of the tuning/report split or the one-time report was broken."""


def load_config(path: Path) -> dict[str, Any]:
    cfg = yaml.safe_load(path.read_text("utf-8"))
    if cfg.get("status") not in ("draft", "frozen"):
        raise DetectError(f"{path}: status must be draft or frozen")
    return cfg


def run_hash(cfg: dict[str, Any], simulation_id: str) -> str:
    """Identity of a run: config without `status`, plus the simulation (like D6)."""
    body = {k: v for k, v in cfg.items() if k != "status"}
    text = json.dumps({"config": body, "simulation_id": simulation_id}, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _purpose(sim_root: Path, simulation_id: str) -> str:
    manifest = sim_root / simulation_id / "simulation_manifest.yaml"
    if not manifest.exists():
        raise DetectError(f"{manifest} not found; run `make simulate` for this config first")
    return yaml.safe_load(manifest.read_text("utf-8"))["config"]["purpose"]


def _days(kpis: dict[str, pd.DataFrame]) -> float:
    b = kpis["provider_15m"]["bucket_start"]
    return ((b.max() - b.min()) / pd.Timedelta("15min") + 1) / 96


def score_and_evaluate(
    cfg: dict[str, Any], kpis: dict[str, pd.DataFrame], labels: list[dict[str, Any]]
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    """Alerts, incidents (both detectors) and their evaluation against `labels`."""
    alerts = detect(kpis, cfg["detectors"])
    incidents = merge_incidents(alerts, cfg["incidents"]["max_gap_buckets"])
    days = _days(kpis)
    grace = cfg["evaluation"]["grace_minutes"]
    result = {
        d: evaluate([i for i in incidents if i["detector"] == d], labels, days, grace)
        for d in DETECTORS
    }
    return alerts, incidents, result


def _write_run(
    out: Path, cfg: dict[str, Any], sid: str, stage: str, alerts: pd.DataFrame,
    incidents: list[dict[str, Any]], result: dict[str, Any], extra: dict[str, Any],
) -> None:  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    alerts.to_parquet(out / "scores.parquet", index=False)
    (out / "incidents.json").write_text(json.dumps(incidents, indent=2) + "\n", encoding="utf-8")
    body = {"simulation_id": sid, "stage": stage, **extra, "detectors": result}
    (out / "evaluation.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    (out / "git_sha.txt").write_text(sha + "\n", encoding="utf-8")
    libs = ", ".join(f"{p} {version(p)}" for p in ("numpy", "pandas", "pyarrow"))
    (out / "environment.txt").write_text(
        f"python {platform.python_version()}, {libs}\n", encoding="utf-8"
    )


def cmd_detect(cfg: dict[str, Any], kpi_root: Path, sim_root: Path, out_root: Path) -> Path:
    sid = cfg["simulations"]["tuning"]
    if _purpose(sim_root, sid) != "tuning":
        raise DetectError(f"{sid} is not a tuning simulation; detect only runs on tuning")
    kpis = load_kpis(kpi_root, sid)
    alerts, incidents, result = score_and_evaluate(cfg, kpis, load_labels(sim_root / sid))
    run_id = "det-" + run_hash(cfg, sid)[:12]
    out = out_root / "detections" / run_id
    _write_run(out, cfg, sid, "tuning", alerts, incidents, result, {"run_id": run_id})
    return out


def tune(
    cfg: dict[str, Any], kpis: dict[str, pd.DataFrame], labels: list[dict[str, Any]]
) -> pd.DataFrame:
    """Every grid point of both detectors with its tuning result, best first per detector.

    Best = most anomalies detected (right target) with false_per_day <= max_false_per_day;
    ties: shorter mean delay, then the higher (more conservative) threshold.
    """
    rows = []
    days, grace = _days(kpis), cfg["evaluation"]["grace_minutes"]
    gap = cfg["incidents"]["max_gap_buckets"]
    for pool in GRID["pooled"]["pool_buckets"]:
        params = {**cfg["detectors"], "pooled": {"pool_buckets": pool, "threshold": 0.0},
                  "robust_z": {"threshold": 0.0}}  # fmt: skip
        alerts = detect(kpis, params)
        for det in DETECTORS:
            if det == "robust_z" and pool != GRID["pooled"]["pool_buckets"][0]:
                continue  # D-A does not pool; score it once
            mine = alerts[alerts["detector"] == det]
            for thr in GRID[det]["threshold"]:
                flagged = mine.assign(alert=mine["score"].fillna(-1e9) > thr)
                ev = evaluate(merge_incidents(flagged, gap), labels, days, grace)
                rows.append(
                    {
                        "detector": det,
                        "threshold": thr,
                        "pool_buckets": pool if det == "pooled" else None,
                        "detected": ev["detected"],
                        "detected_any_target": ev["detected_any_target"],
                        "false_per_day": ev["false_per_day"],
                        "mean_delay_minutes": ev["mean_delay_minutes"],
                        "missed": ",".join(
                            a["anomaly_id"] for a in ev["anomalies"] if not a["detected"]
                        ),
                    }
                )
    grid = pd.DataFrame(rows)
    grid["feasible"] = grid["false_per_day"] <= cfg["evaluation"]["max_false_per_day"]
    grid["_delay"] = grid["mean_delay_minutes"].fillna(1e9)
    grid = grid.sort_values(
        ["detector", "feasible", "detected", "_delay", "threshold"],
        ascending=[True, False, False, True, False],
    )
    return grid.drop(columns="_delay").reset_index(drop=True)


def cmd_detect_report(
    cfg: dict[str, Any], kpi_root: Path, sim_root: Path, out_root: Path, force: bool
) -> Path:
    if cfg["status"] != "frozen":
        raise DetectError("detect-report needs a config with status: frozen (owner only, D5)")
    sid = cfg["simulations"]["report"]
    if _purpose(sim_root, sid) != "report":
        raise DetectError(f"{sid} is not a report simulation")
    h = run_hash(cfg, sid)
    registry = out_root / "detect_report_runs.json"
    runs = json.loads(registry.read_text("utf-8")) if registry.exists() else []
    if any(r["hash"] == h for r in runs) and not force:
        raise DetectError(
            f"this frozen config was already evaluated on {sid} (hash {h[:12]}); "
            "the report simulation is used once. Use --force only with a written reason."
        )
    kpis = load_kpis(kpi_root, sid)
    alerts, incidents, result = score_and_evaluate(cfg, kpis, load_labels(sim_root / sid))
    run_id = "det-" + h[:12]
    extra: dict[str, Any] = {"run_id": run_id}
    if force and any(r["hash"] == h for r in runs):
        extra["warning"] = "forced re-run on the report simulation; disclose in the report"
    out = out_root / "detections" / run_id / "report"
    _write_run(out, cfg, sid, "report", alerts, incidents, result, extra)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    runs.append({"hash": h, "run_id": run_id, "simulation_id": sid, "at": stamp, "forced": force})
    registry.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kpi")
    k.add_argument("--sim", required=True)
    for name in ("detect", "tune", "detect-report"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        if name == "detect-report":
            p.add_argument("--force", action="store_true")
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS)
    args = parser.parse_args(argv)
    kpi_root, sim_root = args.artifacts_dir / "kpi", args.artifacts_dir / "simulations"
    try:
        if args.cmd == "kpi":
            from synthetic_generator.ingest import connect

            from payment_reliability.kpi import export_kpis

            with connect() as conn:
                print(export_kpis(conn, args.sim, kpi_root))
            return 0
        cfg = load_config(args.config)
        if args.cmd == "detect":
            out = cmd_detect(cfg, kpi_root, sim_root, args.artifacts_dir)
        elif args.cmd == "tune":
            sid = cfg["simulations"]["tuning"]
            if _purpose(sim_root, sid) != "tuning":
                raise DetectError(f"{sid} is not a tuning simulation")
            grid = tune(cfg, load_kpis(kpi_root, sid), load_labels(sim_root / sid))
            out = args.artifacts_dir / "tuning" / sid
            out.mkdir(parents=True, exist_ok=True)
            grid.to_csv(out / "grid.csv", index=False)
            print(grid.groupby("detector").head(3).to_string(index=False))
        else:
            out = cmd_detect_report(cfg, kpi_root, sim_root, args.artifacts_dir, args.force)
    except (DetectError, KpiError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
