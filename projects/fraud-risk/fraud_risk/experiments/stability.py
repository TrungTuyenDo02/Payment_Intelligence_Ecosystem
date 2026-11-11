"""Stage G / G05: how stable are the model and its inputs over weeks and groups? (`make stability`)

EXPLORATORY: development data only (train + validation). Test weeks are never used.

| table      | what it shows                                                                    |
| ---------- | -------------------------------------------------------------------------------- |
| weekly     | rows, fraud rate, PR-AUC and recall at FPR 5% per week; train weeks are          |
|            | in-sample (the model was fitted on them), so only a description                  |
| groups     | the same metrics per `ProductCD` and `card6` value on validation; groups with    |
|            | fewer than `min_frauds` frauds are flagged "small sample, no conclusion"         |
| psi        | population stability index of a few inputs per week vs all of train             |
| missing    | share of missing values per week for every model input that has any              |

PSI = sum over bins of (cur - ref) * ln(cur / ref), bins = deciles of the TRAIN values (ties merge
bins; missing values are their own bin; empty shares are floored at 1e-4). The 0.1 / 0.25 reading
is a convention, not a test.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dataset_management.manifest import DatasetFileNotFoundError  # noqa: E402

from fraud_risk.evaluation.metrics import pr_auc, recall_at_fpr  # noqa: E402
from fraud_risk.evaluation.run_log import run_id_from_hash, write_json  # noqa: E402
from fraud_risk.experiments.calibration import (  # noqa: E402
    REPO_ROOT,
    experiment_hash,
    write_common,
)
from fraud_risk.experiments.decision_data import (  # noqa: E402
    DevData,
    ReproductionError,
    fmt,
    md_table,
    prepare,
)
from fraud_risk.scripts.config import StabilityConfig, _load  # noqa: E402
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data  # noqa: E402

DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "stability.yaml"
EPS = 1e-4
MODEL = "gbm"
NOTE = (
    "Exploratory (thăm dò): development data only. Train weeks are in-sample for the model "
    "(description only). Validation was used before, so it may be optimistic."
)


def quantile_edges(reference: pd.Series, bins: int) -> np.ndarray:
    """Inner bin edges: unique quantiles k / bins of the non-missing reference values."""
    values = reference.dropna().to_numpy(dtype=float)
    return np.unique(np.quantile(values, np.arange(1, bins) / bins))


def _shares(values: pd.Series, edges: np.ndarray) -> np.ndarray:
    x = values.to_numpy(dtype=float)
    idx = np.where(np.isnan(x), len(edges) + 1, np.searchsorted(edges, x, side="left"))
    counts = np.bincount(idx.astype(int), minlength=len(edges) + 2).astype(float)
    shares = counts / counts.sum()
    return np.where(shares == 0, EPS, shares)


def psi(reference: pd.Series, current: pd.Series, edges: np.ndarray) -> float:
    """Population stability index of `current` against `reference` on fixed bins."""
    ref, cur = _shares(reference, edges), _shares(current, edges)
    return float(np.sum((cur - ref) * np.log(cur / ref)))


def _metrics(rows: pd.DataFrame, target: float) -> dict[str, Any]:
    y, s = rows["y"], rows[f"score_{MODEL}"]
    both = 0 < y.sum() < len(y)
    return {
        "rows": len(rows),
        "frauds": int(y.sum()),
        "prevalence": float(y.mean()),
        "pr_auc": pr_auc(y, s) if both else None,
        "recall_at_fpr": recall_at_fpr(y, s, target)["recall"] if both else None,
    }


def run_stability(data: DevData, cfg: StabilityConfig) -> dict[str, Any]:
    """G05 tables. Pure: writes nothing, sees only train + validation rows."""
    st = cfg.stability
    frame = data.frame
    feats = data.features
    raw_inputs = [c for c in cfg.features.numeric + cfg.features.categorical if c in feats]
    train_rows = frame.index[frame["part"] == "train"]
    edges = {c: quantile_edges(feats.loc[train_rows, c], st.psi_bins) for c in st.psi_columns}

    weekly = []
    for part, key in (("train", "train_week"), ("valid", "week")):
        rows_part = frame[frame["part"] == part]
        for week, rows in rows_part.groupby(key):
            f = feats.loc[rows.index]
            weekly.append({
                "part": part, "week": int(week), "in_sample": part == "train",
                "first_day": int(rows["day"].min()), "last_day": int(rows["day"].max()),
                "blocks": sorted(b for b in set(rows["block"]) if b),
                **_metrics(rows, st.fpr_target),
                "psi": {c: psi(feats.loc[train_rows, c], f[c], edges[c]) for c in st.psi_columns},
                "missing": {c: float(f[c].isna().mean()) for c in raw_inputs},
            })  # fmt: skip
    with_missing = [c for c in raw_inputs if any(w["missing"][c] > 0 for w in weekly)]
    for w in weekly:
        w["missing"] = {c: w["missing"][c] for c in with_missing}

    valid = frame.loc[data.valid]
    groups = []
    for column in st.groups:
        values = valid[column].fillna("(thiếu)")
        for value, rows in valid.groupby(values):
            m = _metrics(rows, st.fpr_target)
            groups.append({
                "column": column, "value": str(value), **m,
                "small_sample": m["frauds"] < st.min_frauds,
            })  # fmt: skip

    permuted = np.random.default_rng(cfg.seed).permutation(valid["y"].to_numpy())
    return {
        "note": NOTE,
        "valid": _metrics(valid, st.fpr_target),
        "weekly": weekly,
        "groups": groups,
        "psi_edges": {c: e.tolist() for c, e in edges.items()},
        "self_checks": {
            "permuted_valid_pr_auc": pr_auc(permuted, valid[f"score_{MODEL}"]),
            "valid_prevalence": float(valid["y"].mean()),
        },
    }


def summary_markdown(run_id: str, res: dict[str, Any]) -> str:
    lines = [f"# G05 độ ổn định — `{run_id}` (thăm dò)", "", res["note"], ""]
    psi_cols = list(res["weekly"][0]["psi"])
    miss_cols = list(res["weekly"][0]["missing"])
    header = ["Phần", "Tuần", "Ngày", "Khối", "Dòng", "Gian lận", "Tỷ lệ", "PR-AUC",
              "Recall@FPR5%"] + [f"PSI {c}" for c in psi_cols]  # fmt: skip
    rows = [
        [("train (trong mẫu)" if w["in_sample"] else "validation"), f"W{w['week']}",
         f"{w['first_day']}–{w['last_day']}", "/".join(w["blocks"]), w["rows"], w["frauds"],
         fmt(w["prevalence"] * 100, 2) + "%", fmt(w["pr_auc"], 3), fmt(w["recall_at_fpr"], 3)]
        + [fmt(w["psi"][c], 3) for c in psi_cols]
        for w in res["weekly"]
    ]  # fmt: skip
    lines += ["## Theo tuần", "", *md_table(header, rows), ""]
    header = ["Phần", "Tuần"] + [f"Thiếu {c}" for c in miss_cols]
    rows = [
        [("train" if w["in_sample"] else "validation"), f"W{w['week']}"]
        + [fmt(w["missing"][c] * 100, 1) + "%" for c in miss_cols]
        for w in res["weekly"]
    ]
    lines += ["## Tỷ lệ thiếu theo tuần", "", *md_table(header, rows), ""]
    header = ["Cột", "Giá trị", "Dòng", "Gian lận", "Tỷ lệ", "PR-AUC", "Recall@FPR5%", "Ghi chú"]
    rows = [
        [g["column"], g["value"], g["rows"], g["frauds"], fmt(g["prevalence"] * 100, 2) + "%",
         fmt(g["pr_auc"], 3), fmt(g["recall_at_fpr"], 3),
         "cỡ mẫu nhỏ, không kết luận" if g["small_sample"] else ""]
        for g in res["groups"]
    ]  # fmt: skip
    v = res["valid"]
    lines += [
        f"## Theo nhóm (validation; toàn bộ: PR-AUC {fmt(v['pr_auc'], 3)}, "
        f"recall@FPR5% {fmt(v['recall_at_fpr'], 3)})",
        "",
        *md_table(header, rows),
        "",
    ]
    sc = res["self_checks"]
    lines += [
        "## Tự kiểm tra",
        "",
        f"- Hoán vị nhãn validation: PR-AUC {fmt(sc['permuted_valid_pr_auc'])}, "
        f"tỷ lệ gian lận {fmt(sc['valid_prevalence'])} (mức ngẫu nhiên).",
        "",
    ]
    return "\n".join(lines)


def stability_figure(res: dict[str, Any], path: Path) -> None:
    """Fraud rate, PR-AUC and PSI per week; train weeks (in-sample) shaded."""
    weekly = res["weekly"]
    x = np.arange(len(weekly))
    n_train = sum(w["in_sample"] for w in weekly)
    fig, axes = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(x, [w["prevalence"] * 100 for w in weekly], marker="o", ms=3, color="black")
    axes[0].set_ylabel("Tỷ lệ gian lận (%)", fontsize=8)
    axes[1].plot(x, [w["pr_auc"] for w in weekly], marker="o", ms=3, color="#2f6fb0",
                 label="PR-AUC")  # fmt: skip
    axes[1].plot(x, [w["recall_at_fpr"] for w in weekly], marker="s", ms=3, color="#d1782a",
                 label="Recall @ FPR 5%")  # fmt: skip
    axes[1].legend(frameon=False, fontsize=7)
    for c in weekly[0]["psi"]:
        axes[2].plot(x, [w["psi"][c] for w in weekly], marker="o", ms=3, label=c)
    axes[2].axhline(0.1, color="#cccccc", lw=1, ls="--")
    axes[2].axhline(0.25, color="#999999", lw=1, ls="--")
    axes[2].set_ylabel("PSI so với train", fontsize=8)
    axes[2].legend(frameon=False, fontsize=7, ncol=4)
    for ax in axes:
        ax.axvspan(-0.5, n_train - 0.5, color="#eeeeee", lw=0)
        ax.tick_params(labelsize=7)
    labels = [f"{'T' if w['in_sample'] else 'V'}{w['week']}" for w in weekly]
    axes[2].set_xticks(x, labels)
    axes[2].set_xlabel("Tuần (nền xám: train, trong mẫu; V: validation)", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def load_stability_config(path: Path) -> tuple[StabilityConfig, dict[str, Any], str]:
    return _load(path, StabilityConfig)


def run(
    config_path: Path, *, data_dir: Path | None = None, manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
) -> Path:  # fmt: skip
    """Load and check the data, run G05, write `artifacts/experiments/stab-<hash>/`."""
    cfg, raw, text = load_stability_config(config_path)
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    dev = prepare(data.X, data.y, data.time, cfg)
    run_hash = experiment_hash(raw, cfg.seed, manifest.checksum, dev)
    run_id = run_id_from_hash(run_hash).replace("run-", "stab-")
    res = run_stability(dev, cfg)
    out = artifacts_dir / "experiments" / run_id
    write_common(out, text)
    write_json(out / "results.json", {"run_id": run_id, "run_hash": run_hash, **res})
    (out / "summary.md").write_text(summary_markdown(run_id, res), encoding="utf-8")
    stability_figure(res, out / "stability.png")
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Stage G stability (development data only)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    try:
        out = run(args.config, data_dir=args.data_dir, manifest_path=args.manifest,
                  artifacts_dir=args.artifacts_dir)  # fmt: skip
    except DatasetFileNotFoundError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    except (*KNOWN_ERRORS, ReproductionError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    print(json.dumps({"experiment folder": str(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
