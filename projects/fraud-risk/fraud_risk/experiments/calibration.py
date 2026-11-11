"""Stage G / G03: can the scores be read as probabilities? (`make calibration`)

EXPLORATORY: development data only (train + validation); validation was already used before.

Both fixed models (GBM, Logistic Regression) are trained with `class_weight="balanced"`, which
inflates the odds of fraud by n_legit / n_fraud. Three ways to turn a score into a probability:

| method        | fitted on | what it does                                                       |
| ------------- | --------- | ------------------------------------------------------------------ |
| `raw`         | -         | the score as is                                                    |
| `prior_shift` | train     | logit + log(pi / (1 - pi)), pi = train fraud rate: undoes the      |
|               |           | balanced weights (exact for a well-specified LR; approximate, GBM) |
| `platt`       | V1 labels | logistic regression on the logit of the score                      |

All three are monotone, so PR-AUC and any top-N policy stay the same; only cost thresholds
that read the probability change. The method used later (G04) is the one with the lowest log
loss on V2. V3 is reported, never used to fit or choose.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dataset_management.manifest import DatasetFileNotFoundError  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.metrics import brier_score_loss, log_loss  # noqa: E402

from fraud_risk.evaluation.metrics import pr_auc  # noqa: E402
from fraud_risk.evaluation.run_log import (  # noqa: E402
    compute_run_hash,
    environment_text,
    git_sha,
    run_id_from_hash,
    utc_now,
    write_execution,
    write_json,
)
from fraud_risk.experiments.decision_data import (  # noqa: E402
    Block,
    DevData,
    ReproductionError,
    block_summary,
    blocks,
    check_reproduction,
    fmt,
    md_table,
    prepare,
    require_role,
    rolling_windows,
)
from fraud_risk.scripts.config import CalibrationConfig, _load  # noqa: E402
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "calibration.yaml"
EPS = 1e-6
NOTE = (
    "Exploratory (thăm dò): development data only; validation was used before (GBM grid, "
    "leakage experiment, history features), so these numbers may be optimistic."
)


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-z))


def prior_shift(scores: np.ndarray, prevalence: float) -> np.ndarray:
    """Undo balanced class weights: the weighted odds are the true odds times (1 - pi) / pi."""
    return sigmoid(logit(scores) + np.log(prevalence / (1 - prevalence)))


@dataclass(frozen=True)
class Calibrator:
    """A monotone map from score to probability."""

    method: str
    params: dict[str, float]

    @property
    def monotone(self) -> bool:
        """Increasing map (keeps the ranking). Platt on a tiny block can fit a slope <= 0."""
        return self.method != "platt" or self.params["slope"] > 0

    def apply(self, scores: np.ndarray) -> np.ndarray:
        if self.method == "raw":
            return np.asarray(scores, dtype=float)
        if self.method == "prior_shift":
            return prior_shift(scores, self.params["prevalence"])
        if self.method == "platt":
            return sigmoid(self.params["slope"] * logit(scores) + self.params["intercept"])
        raise ValueError(f"unknown calibration method: {self.method}")


def fit_calibrator(method: str, data: DevData, model: str, block: Block) -> Calibrator:
    """Fit `method` for `model`; `block` must be a calibrate block (V1 or a rolling week k)."""
    require_role(block, "calibrate")
    if method == "raw":
        return Calibrator("raw", {})
    if method == "prior_shift":
        return Calibrator("prior_shift", {"prevalence": data.train_prevalence})
    if method == "platt":
        rows = data.frame.loc[block.index]
        x = logit(rows[f"score_{model}"].to_numpy()).reshape(-1, 1)
        fit = LogisticRegression(C=1e6, max_iter=1000).fit(x, rows["y"].to_numpy())
        params = {"slope": float(fit.coef_[0, 0]), "intercept": float(fit.intercept_[0])}
        return Calibrator("platt", params)  # slope <= 0 is flagged by `monotone`, never chosen
    raise ValueError(f"unknown calibration method: {method}")


def calibration_metrics(y: Any, p: Any, bins: int) -> dict[str, Any]:
    """Brier score, log loss, PR-AUC and a quantile-bin reliability table."""
    y, p = np.asarray(y, dtype=int), np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    frame = pd.DataFrame({"y": y, "p": p})
    frame["bin"] = pd.qcut(frame["p"].rank(method="first"), bins, labels=False)
    table = frame.groupby("bin").agg(
        rows=("y", "size"), observed=("y", "mean"), mean_pred=("p", "mean"),
        low=("p", "min"), high=("p", "max"),
    )  # fmt: skip
    return {
        "rows": len(y),
        "frauds": int(y.sum()),
        "prevalence": float(y.mean()),
        "mean_pred": float(p.mean()),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, p, labels=[0, 1])),
        "pr_auc": pr_auc(y, p) if 0 < y.sum() < len(y) else None,
        "reliability": table.reset_index(drop=True).to_dict("records"),
    }


def _evaluate(cal: Calibrator, data: DevData, model: str, index: pd.Index, bins: int) -> dict:
    rows = data.frame.loc[index]
    return calibration_metrics(rows["y"], cal.apply(rows[f"score_{model}"].to_numpy()), bins)


def choose(losses: dict[str, float], fitted: dict[str, Calibrator]) -> str:
    """Monotone method with the lowest loss on the select block (ties: config order)."""
    return min((m for m in losses if fitted[m].monotone), key=lambda m: losses[m])


def run_calibration(data: DevData, cfg: CalibrationConfig) -> dict[str, Any]:
    """G03 main analysis + rolling windows + self checks. Pure: writes nothing."""
    c = cfg.calibration
    main = blocks(data)
    models = [m for m in ("gbm", "logistic") if f"score_{m}" in data.frame]
    out: dict[str, Any] = {}
    valid = data.frame.loc[data.valid]
    for model in models:
        per_method: dict[str, Any] = {}
        fitted_v1 = {m: fit_calibrator(m, data, model, main["V1"]) for m in c.methods}
        for method, cal in fitted_v1.items():
            per_method[method] = {
                "params": cal.params,
                "monotone": cal.monotone,
                "blocks": {
                    name: {
                        **_evaluate(cal, data, model, b.index, c.bins),
                        "in_sample": name == "V1" and method == "platt",
                    }
                    for name, b in main.items()
                },  # fmt: skip
                "weekly": [
                    {
                        "week": int(w),
                        "blocks": sorted(set(rows["block"])),
                        **{
                            k: v
                            for k, v in _evaluate(cal, data, model, rows.index, c.bins).items()
                            if k != "reliability"
                        },
                    }
                    for w, rows in valid.groupby("week")
                ],  # fmt: skip
            }
        loss_v2 = {m: r["blocks"]["V2"][c.select_by] for m, r in per_method.items()}
        per_method["chosen"] = choose(loss_v2, fitted_v1)
        out[model] = per_method

    rolling = []
    for window in rolling_windows(data):
        entry: dict[str, Any] = {
            "window": window.name,
            "calibrate": window.calibrate.name,
            "select": window.select.name,
            "evaluate": window.evaluate.name,
        }
        for model in models:
            fitted = {m: fit_calibrator(m, data, model, window.calibrate) for m in c.methods}
            sel = {m: _evaluate(f, data, model, window.select.index, c.bins)[c.select_by]
                   for m, f in fitted.items()}  # fmt: skip
            ev = {m: _evaluate(f, data, model, window.evaluate.index, c.bins)
                  for m, f in fitted.items()}  # fmt: skip
            entry[model] = {
                "chosen": choose(sel, fitted),
                "evaluate": {m: {"brier": e["brier"], "log_loss": e["log_loss"],
                                 "mean_pred": e["mean_pred"], "prevalence": e["prevalence"]}
                             for m, e in ev.items()},
            }  # fmt: skip
        rolling.append(entry)

    v3 = data.frame.loc[main["V3"].index]
    permuted = np.random.default_rng(cfg.seed).permutation(v3["y"].to_numpy())
    return {
        "note": NOTE,
        "blocks": block_summary(data),
        "reproduction_valid_pr_auc": check_reproduction(data, cfg),
        "train_prevalence": data.train_prevalence,
        "models": out,
        "rolling": rolling,
        "self_checks": {
            "permuted_v3_pr_auc": pr_auc(permuted, v3["score_gbm"]),
            "v3_prevalence": float(v3["y"].mean()),
        },
    }


# --- output -----------------------------------------------------------------------------------

METHOD_VN = {"raw": "gốc", "prior_shift": "dịch tiên nghiệm", "platt": "sigmoid (Platt)"}
MODEL_VN = {"gbm": "Gradient Boosting", "logistic": "Logistic Regression"}


def summary_markdown(run_id: str, res: dict[str, Any]) -> str:
    """Tables for the report (Vietnamese, numbers with a decimal comma)."""
    lines = [f"# G03 hiệu chỉnh xác suất — `{run_id}` (thăm dò)", "", res["note"], ""]
    lines += md_table(
        ["Khối", "Vai trò", "Ngày", "Dòng", "Gian lận", "Tỷ lệ"],
        [[b["block"], b["role"], f"{b['first_day']}–{b['last_day']}", b["rows"], b["frauds"],
          fmt(b["prevalence"] * 100, 2) + "%"] for b in res["blocks"]],
    )  # fmt: skip
    lines += [
        "",
        f"Tỷ lệ gian lận train (cho dịch tiên nghiệm): {fmt(res['train_prevalence'])}.",
        f"PR-AUC validation của mô hình tái tạo: {res['reproduction_valid_pr_auc']}.",
        "",
    ]
    for model, per in res["models"].items():
        methods = [m for m in per if m != "chosen"]
        rows = [
            [METHOD_VN[m], name + (" (trong mẫu)" if b["in_sample"] else ""), fmt(b["brier"]),
             fmt(b["log_loss"]), fmt(b["mean_pred"]), fmt(b["prevalence"]), fmt(b["pr_auc"], 3)]
            for m in methods for name, b in per[m]["blocks"].items()
        ]  # fmt: skip
        header = ["Phương pháp", "Khối", "Brier", "Log loss", "Xác suất TB", "Tỷ lệ thật", "PR-AUC"]
        lines += [f"## {MODEL_VN[model]}", "", *md_table(header, rows), ""]
        lines += [f"Chọn trên V2 (log loss nhỏ nhất): **{METHOD_VN[per['chosen']]}**.", ""]
        header = ["Tuần", "Khối", "Tỷ lệ thật"]
        header += [f"{k} {METHOD_VN[m]}" for m in methods for k in ("TB", "Log loss")]
        weeks = per[methods[0]]["weekly"]
        rows = [
            [f"W{w['week']}", "/".join(w["blocks"]), fmt(w["prevalence"])]
            + [fmt(per[m]["weekly"][i][k]) for m in methods for k in ("mean_pred", "log_loss")]
            for i, w in enumerate(weeks)
        ]
        lines += ["Theo tuần (validation):", "", *md_table(header, rows), ""]
    rows = []
    for w in res["rolling"]:
        for model in res["models"]:
            losses = ", ".join(
                f"{METHOD_VN[m]} {fmt(v['log_loss'])}" for m, v in w[model]["evaluate"].items()
            )
            roles = f"{w['calibrate']}/{w['select']}/{w['evaluate']}"
            chosen = METHOD_VN[w[model]["chosen"]]
            rows.append([w["window"], roles, MODEL_VN[model], chosen, losses])
    header = ["Cửa sổ", "Hiệu chỉnh / chọn / đánh giá", "Mô hình", "Chọn", "Log loss đánh giá"]
    lines += ["## Cửa sổ cuốn chiếu (độ nhạy)", "", *md_table(header, rows), ""]
    sc = res["self_checks"]
    lines += [
        "## Tự kiểm tra",
        "",
        f"- Hoán vị nhãn V3: PR-AUC của GBM {fmt(sc['permuted_v3_pr_auc'])}, "
        f"tỷ lệ gian lận V3 {fmt(sc['v3_prevalence'])} (mức ngẫu nhiên).",
        "- Hiệu chỉnh đơn điệu: PR-AUC giống nhau giữa các phương pháp trong cùng khối.",
        "",
    ]
    return "\n".join(lines)


def reliability_figure(res: dict[str, Any], path: Path) -> None:
    """Reliability on V3 (left: GBM, right: LR) and weekly observed vs mean predicted (GBM)."""
    models = list(res["models"])
    fig, axes = plt.subplots(1, len(models) + 1, figsize=(4.2 * (len(models) + 1), 4))
    colors = {"raw": "#9aa5b1", "prior_shift": "#2f6fb0", "platt": "#d1782a"}
    for ax, model in zip(axes, models, strict=False):
        per = res["models"][model]
        for method in (m for m in per if m != "chosen"):
            rel = per[method]["blocks"]["V3"]["reliability"]
            ax.plot([r["mean_pred"] for r in rel], [r["observed"] for r in rel], marker="o",
                    ms=3, color=colors[method], label=METHOD_VN[method])  # fmt: skip
        ax.plot([0, 1], [0, 1], color="#cccccc", lw=1, ls="--")
        ax.set_xscale("symlog", linthresh=0.01)
        ax.set_yscale("symlog", linthresh=0.01)
        ax.set_title(f"{MODEL_VN[model]} · V3", fontsize=9)
        ax.set_xlabel("Xác suất dự đoán trung bình (bin)", fontsize=8)
        ax.set_ylabel("Tỷ lệ gian lận thật", fontsize=8)
        ax.legend(frameon=False, fontsize=7)
    ax = axes[-1]
    per = res["models"]["gbm"]
    weeks = [w["week"] for w in per["raw"]["weekly"]]
    ax.plot(weeks, [w["prevalence"] for w in per["raw"]["weekly"]], color="black", marker="s",
            ms=3, label="Tỷ lệ thật")  # fmt: skip
    for method in (m for m in per if m not in ("chosen", "raw")):
        ax.plot(weeks, [w["mean_pred"] for w in per[method]["weekly"]], marker="o", ms=3,
                color=colors[method], label=f"TB {METHOD_VN[method]}")  # fmt: skip
    ax.set_title("Gradient Boosting · theo tuần validation", fontsize=9)
    ax.set_xlabel("Tuần", fontsize=8)
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def load_calibration_config(path: Path) -> tuple[CalibrationConfig, dict[str, Any], str]:
    return _load(path, CalibrationConfig)


def experiment_hash(raw: dict[str, Any], seed: int, checksum: str, data: DevData) -> str:
    """Config, seed, dataset checksum, frozen split bounds and block days (spec section 6)."""
    bounds = {**data.split_boundaries, "blocks": raw["blocks"]}
    return compute_run_hash(raw, seed, checksum, bounds)


def write_common(out: Path, text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(text, encoding="utf-8")
    (out / "environment.txt").write_text(environment_text(), encoding="utf-8")
    (out / "git_sha.txt").write_text(git_sha(REPO_ROOT) + "\n", encoding="utf-8")


def run(
    config_path: Path, *, data_dir: Path | None = None, manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
) -> Path:  # fmt: skip
    """Load and check the data, run G03, write `artifacts/experiments/cal-<hash>/`."""
    started = utc_now()
    cfg, raw, text = load_calibration_config(config_path)
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    dev = prepare(data.X, data.y, data.time, cfg)
    run_hash = experiment_hash(raw, cfg.seed, manifest.checksum, dev)
    run_id = run_id_from_hash(run_hash).replace("run-", "cal-")
    res = run_calibration(dev, cfg)
    out = artifacts_dir / "experiments" / run_id
    write_common(out, text)
    write_json(out / "results.json", {"run_id": run_id, "run_hash": run_hash, **res})
    (out / "summary.md").write_text(summary_markdown(run_id, res), encoding="utf-8")
    reliability_figure(res, out / "reliability.png")
    write_execution(out, run_id, started, REPO_ROOT)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Stage G calibration (development data only)")
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
