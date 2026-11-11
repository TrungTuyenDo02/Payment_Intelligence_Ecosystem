"""Stage G / G04: from scores to alerts under ASSUMED costs (`make policy`).

EXPLORATORY: development data only; validation was used before, so numbers may be optimistic.
This is a sensitivity analysis over assumed costs, NOT a return-on-investment estimate.

Cost of a decision (relative units of TransactionAmt, all assumptions):
    missed fraud  -> loss_rate * TransactionAmt
    every alert   -> c_review
    false alert   -> + c_friction

| policy            | chosen on | decision on V3                                                |
| ----------------- | --------- | ------------------------------------------------------------- |
| `none`            | -         | no alert (reference: every fraud is missed)                   |
| `max_f1`          | V2        | score >= threshold with the best F1 on V2 (Stage E rule)      |
| `cost_v2`         | V2        | score >= threshold with the lowest total cost on V2           |
| `rule_raw`        | -         | alert if s*loss_rate*amount > c_review + (1-s)*c_friction,    |
|                   |           | with the RAW score s read as if it were a probability         |
| `rule_calibrated` | V1 + V2   | same rule with the calibrated probability (method as in G03)  |
| `top_N`           | -         | every day, the N% highest scores of that day                  |

A threshold on calibrated scores chosen on V2 gives the same alerts as `cost_v2` (calibration
is monotone); this is checked, not reported twice. Intervals: bootstrap of whole days and of
whole `card1` groups (rows of one day or one card are correlated), never of single rows.
"""

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dataset_management.manifest import DatasetFileNotFoundError

from fraud_risk.evaluation.metrics import recall_at_fpr, select_threshold, threshold_metrics
from fraud_risk.evaluation.run_log import run_id_from_hash, write_json
from fraud_risk.experiments.calibration import (
    REPO_ROOT,
    calibration_metrics,
    choose,
    experiment_hash,
    fit_calibrator,
    write_common,
)
from fraud_risk.experiments.decision_data import (
    Block,
    DevData,
    ReproductionError,
    block_summary,
    blocks,
    fmt,
    md_table,
    prepare,
    require_role,
    rolling_windows,
)
from fraud_risk.scripts.config import PolicyConfig, _load
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data

DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "policy.yaml"
MODEL = "gbm"
NOTE = (
    "Exploratory (thăm dò), development data only. Costs are assumptions in relative units of "
    "TransactionAmt: a sensitivity analysis, not ROI. Labels are assumed known at once (D3)."
)


@dataclass(frozen=True)
class Cost:
    loss_rate: float
    c_review: float
    c_friction: float

    @property
    def key(self) -> str:
        return f"L{self.loss_rate:g}/R{self.c_review:g}/F{self.c_friction:g}"


def cost_grid(cfg: PolicyConfig) -> list[Cost]:
    g = cfg.policy.cost
    return [Cost(*c) for c in itertools.product(g.loss_rate, g.c_review, g.c_friction)]


def row_costs(y: np.ndarray, amount: np.ndarray, alert: np.ndarray, cost: Cost) -> np.ndarray:
    """Cost of each row's decision."""
    missed = (~alert) & (y == 1)
    false_alert = alert & (y == 0)
    return missed * cost.loss_rate * amount + alert * cost.c_review + false_alert * cost.c_friction


def outcome(y: Any, amount: Any, alert: Any, cost: Cost) -> dict[str, Any]:
    """Counts, amounts and total cost of one set of alerts."""
    y, amount, alert = np.asarray(y), np.asarray(amount, dtype=float), np.asarray(alert, bool)
    tp, fp = int((alert & (y == 1)).sum()), int((alert & (y == 0)).sum())
    frauds, legit = int((y == 1).sum()), int((y == 0).sum())
    fraud_amount = float(amount[y == 1].sum())
    caught_amount = float(amount[alert & (y == 1)].sum())
    return {
        "alerts": int(alert.sum()),
        "tp": tp,
        "fp": fp,
        "frauds": frauds,
        "recall": tp / frauds if frauds else 0.0,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "fpr": fp / legit if legit else 0.0,
        "caught_amount": caught_amount,
        "fraud_amount": fraud_amount,
        "recall_amount": caught_amount / fraud_amount if fraud_amount else 0.0,
        "cost": float(row_costs(y, amount, alert, cost).sum()),
    }


def cost_threshold(y: Any, scores: Any, amount: Any, cost: Cost) -> float:
    """Threshold (alert if score >= t) with the lowest total cost; +inf means no alert."""
    y, s, a = np.asarray(y), np.asarray(scores, dtype=float), np.asarray(amount, dtype=float)
    order = np.argsort(-s, kind="stable")
    y, s, a = y[order], s[order], a[order]
    fraud_loss = np.where(y == 1, cost.loss_rate * a, 0.0)
    k = np.arange(1, len(s) + 1)  # alert the top k rows
    total = (
        fraud_loss.sum() - np.cumsum(fraud_loss) + cost.c_review * k
        + cost.c_friction * np.cumsum(y == 0)
    )  # fmt: skip
    valid = np.append(s[:-1] > s[1:], True)  # cut only between distinct scores
    best = int(np.argmin(np.where(valid, total, np.inf)))
    if fraud_loss.sum() <= total[best]:
        return math.inf
    return float(s[best])


def bayes_rule(p: np.ndarray, amount: np.ndarray, cost: Cost) -> np.ndarray:
    """Alert when the expected loss avoided exceeds the expected review + friction cost."""
    return p * cost.loss_rate * amount > cost.c_review + (1 - p) * cost.c_friction


def top_n_per_day(day: Any, scores: Any, pct: float) -> np.ndarray:
    """Alert the ceil(pct% * n_day) highest scores of each day (ties: earlier row first)."""
    frame = pd.DataFrame({"day": np.asarray(day), "s": np.asarray(scores, dtype=float)})
    frame["rank"] = frame.groupby("day")["s"].rank(method="first", ascending=False)
    budget = np.ceil(frame.groupby("day")["s"].transform("size") * pct / 100)
    return (frame["rank"] <= budget).to_numpy()


def select_thresholds(
    data: DevData, block: Block, costs: list[Cost], fpr_target: float
) -> dict[str, Any]:
    """Every threshold of the policies, chosen on a `select` block only."""
    require_role(block, "select")
    rows = data.frame.loc[block.index]
    y, s, a = rows["y"].to_numpy(), rows[f"score_{MODEL}"].to_numpy(), rows["TransactionAmt"]
    fpr = recall_at_fpr(y, s, fpr_target)
    return {
        "max_f1": select_threshold(y, s, "max_f1"),
        "fpr_target": fpr["threshold"] if fpr["reachable"] else math.inf,
        "cost_v2": {c.key: cost_threshold(y, s, a.to_numpy(), c) for c in costs},
    }


def calibrated(data: DevData, cal_block: Block, sel_block: Block, cfg: PolicyConfig) -> Any:
    """G03 rule: fit each method on the calibrate block, keep the best log loss on select."""
    c = cfg.policy.calibration
    fitted = {m: fit_calibrator(m, data, MODEL, cal_block) for m in c.methods}
    sel = data.frame.loc[sel_block.index]
    losses = {
        m: calibration_metrics(sel["y"], f.apply(sel[f"score_{MODEL}"].to_numpy()), c.bins)[
            c.select_by
        ]
        for m, f in fitted.items()
    }
    return fitted[choose(losses, fitted)]


def policies(
    data: DevData, windows: tuple[Block, Block, Block], cfg: PolicyConfig
) -> tuple[dict[str, Any], dict[str, dict[str, np.ndarray]], pd.DataFrame]:
    """Alerts on the evaluate block per cost key and policy, plus what was selected."""
    cal_block, sel_block, eval_block = windows
    costs = cost_grid(cfg)
    chosen = select_thresholds(data, sel_block, costs, cfg.policy.fpr_target)
    calibrator = calibrated(data, cal_block, sel_block, cfg)
    ev = data.frame.loc[eval_block.index]
    s, a = ev[f"score_{MODEL}"].to_numpy(), ev["TransactionAmt"].to_numpy(dtype=float)
    p = calibrator.apply(s)
    fixed = {
        "none": np.zeros(len(ev), bool),
        "max_f1": s >= chosen["max_f1"],
        **{f"top_{n:g}%": top_n_per_day(ev["day"], s, n) for n in cfg.policy.budgets_pct},
    }
    alerts = {}
    for c in costs:
        alerts[c.key] = {
            **fixed,
            "cost_v2": s >= chosen["cost_v2"][c.key],
            "rule_raw": bayes_rule(s, a, c),
            "rule_calibrated": bayes_rule(p, a, c),
        }
    selected = {**chosen, "calibration": {"method": calibrator.method, **calibrator.params}}
    return selected, alerts, ev


def same_alerts_on_calibrated_scores(data: DevData, cfg: PolicyConfig) -> bool:
    """A V2 cost threshold on calibrated scores gives the same V3 alerts as on raw scores."""
    main = blocks(data)
    cal = calibrated(data, main["V1"], main["V2"], cfg)
    sel, ev = data.frame.loc[main["V2"].index], data.frame.loc[main["V3"].index]
    s_sel, s_ev = sel[f"score_{MODEL}"].to_numpy(), ev[f"score_{MODEL}"].to_numpy()
    for c in cost_grid(cfg):
        t_raw = cost_threshold(sel["y"], s_sel, sel["TransactionAmt"].to_numpy(), c)
        t_cal = cost_threshold(sel["y"], cal.apply(s_sel), sel["TransactionAmt"].to_numpy(), c)
        if not np.array_equal(s_ev >= t_raw, cal.apply(s_ev) >= t_cal):
            return False
    return True


class Bootstrap:
    """Resample whole units (days or card1 groups) of the evaluate rows; seeded."""

    def __init__(self, units: pd.Series, resamples: int, seed: int) -> None:
        codes = pd.factorize(units)[0]
        missing = codes < 0  # no card1: each such row is its own group
        codes[missing] = codes.max() + 1 + np.arange(missing.sum())
        self.codes, n = codes, int(codes.max()) + 1
        rng = np.random.default_rng(seed)
        draws = rng.integers(0, n, size=(resamples, n))
        self.weights = np.stack([np.bincount(d, minlength=n) for d in draws]).astype(float)

    def ci(self, values: np.ndarray) -> list[float]:
        totals = self.weights @ np.bincount(self.codes, weights=values)
        return [float(np.percentile(totals, 2.5)), float(np.percentile(totals, 97.5))]


def evaluate_main(
    data: DevData, cfg: PolicyConfig, alerts: dict, ev: pd.DataFrame
) -> list[dict[str, Any]]:
    """Every policy x cost on V3, with day and card1 intervals for cost and delta vs max_f1."""
    b = cfg.policy.bootstrap
    boots = {
        "day": Bootstrap(ev["day"], b.resamples, b.seed),
        "card1": Bootstrap(ev["card1"], b.resamples, b.seed),
    }
    y, a = ev["y"].to_numpy(), ev["TransactionAmt"].to_numpy(dtype=float)
    rows = []
    for c in cost_grid(cfg):
        base = row_costs(y, a, alerts[c.key]["max_f1"], c)
        for name, alert in alerts[c.key].items():
            per_row = row_costs(y, a, alert, c)
            row = {"cost_key": c.key, **c.__dict__, "policy": name, **outcome(y, a, alert, c)}
            row["delta_vs_max_f1"] = float((per_row - base).sum())
            for unit, boot in boots.items():
                row[f"cost_ci_{unit}"] = boot.ci(per_row)
                row[f"delta_vs_max_f1_ci_{unit}"] = boot.ci(per_row - base)
            rows.append(row)
    return rows


def transfer_test(data: DevData, threshold: float, block: Block, target: float) -> dict:
    """FPR and recall on `block` of a threshold chosen elsewhere, vs the in-block optimum."""
    ev = data.frame.loc[block.index]
    y, s = ev["y"], ev[f"score_{MODEL}"]
    at = threshold_metrics(y, s, threshold)
    oracle = recall_at_fpr(y, s, target)
    return {
        "threshold": threshold,
        "fpr": at["false_positive_rate"],
        "recall": at["recall"],
        "oracle_recall_at_fpr": oracle["recall"],
        "oracle_threshold": oracle["threshold"],
    }


def winners(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Lowest-cost policy per cost key (ties: first in policy order)."""
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["cost_key"] not in best or r["cost"] < best[r["cost_key"]]["cost"]:
            best[r["cost_key"]] = r
    return {k: r["policy"] for k, r in best.items()}


def run_policy(data: DevData, cfg: PolicyConfig) -> dict[str, Any]:
    """G04: V1 calibrate, V2 select, V3 evaluate; rolling windows; self checks. Pure."""
    main = blocks(data)
    triple = (main["V1"], main["V2"], main["V3"])
    selected, alerts, ev = policies(data, triple, cfg)
    v3_rows = evaluate_main(data, cfg, alerts, ev)
    target = cfg.policy.fpr_target

    rolling = []
    for w in rolling_windows(data):
        sel_w, alerts_w, ev_w = policies(data, (w.calibrate, w.select, w.evaluate), cfg)
        y, a = ev_w["y"].to_numpy(), ev_w["TransactionAmt"].to_numpy(dtype=float)
        rows_w = [
            {"cost_key": c.key, "policy": name, "cost": outcome(y, a, al, c)["cost"]}
            for c in cost_grid(cfg) for name, al in alerts_w[c.key].items()
        ]  # fmt: skip
        rolling.append({
            "window": w.name, "calibrate": w.calibrate.name, "select": w.select.name,
            "evaluate": w.evaluate.name, "calibration": sel_w["calibration"]["method"],
            "transfer": transfer_test(data, sel_w["fpr_target"], w.evaluate, target),
            "winners": winners(rows_w), "costs": rows_w,
        })  # fmt: skip

    central = Cost(0.75, 5.0, 1.0)
    permuted = np.random.default_rng(cfg.seed).permutation(ev["y"].to_numpy())
    alert = alerts[central.key]["cost_v2"]
    perm = outcome(permuted, ev["TransactionAmt"].to_numpy(dtype=float), alert, central)
    return {
        "note": NOTE,
        "blocks": block_summary(data),
        "selected": selected,
        "transfer_v3": transfer_test(data, selected["fpr_target"], main["V3"], target),
        "v3": v3_rows,
        "v3_winners": winners(v3_rows),
        "rolling": rolling,
        "self_checks": {
            "calibrated_v2_threshold_same_alerts": same_alerts_on_calibrated_scores(data, cfg),
            "permuted_v3": {
                "cost_key": central.key,
                "policy": "cost_v2",
                "recall": perm["recall"],
                "alert_rate": float(alert.mean()),
            },
        },
    }


# --- output -----------------------------------------------------------------------------------

POLICY_VN = {
    "none": "không cảnh báo",
    "max_f1": "max F1 (mốc)",
    "cost_v2": "ngưỡng chi phí V2",
    "rule_raw": "luật chi phí, điểm gốc",
    "rule_calibrated": "luật chi phí, đã hiệu chỉnh",
}


def _p(name: str) -> str:
    return POLICY_VN.get(name, name.replace("top_", "top "))


def _ci(ci: list[float], d: int = 0) -> str:
    return f"[{fmt(ci[0], d)}; {fmt(ci[1], d)}]"


def summary_markdown(run_id: str, res: dict[str, Any]) -> str:
    sel = res["selected"]
    cal = sel["calibration"]
    lines = [f"# G04 chính sách quyết định — `{run_id}` (thăm dò)", "", res["note"], ""]
    lines += [
        "## Chọn trên V2",
        "",
        f"- Ngưỡng max F1: {fmt(sel['max_f1'])}; ngưỡng cho FPR 5%: {fmt(sel['fpr_target'])}.",
        f"- Hiệu chỉnh (fit V1, chọn V2): {cal['method']}.",
        "",
    ]
    t = res["transfer_v3"]
    rows = [["V2 → V3", fmt(t["threshold"]), fmt(t["fpr"] * 100, 2) + "%", fmt(t["recall"], 3),
             fmt(t["oracle_recall_at_fpr"], 3)]]  # fmt: skip
    for w in res["rolling"]:
        t = w["transfer"]
        rows.append([f"{w['window']}: {w['select']} → {w['evaluate']}", fmt(t["threshold"]),
                     fmt(t["fpr"] * 100, 2) + "%", fmt(t["recall"], 3),
                     fmt(t["oracle_recall_at_fpr"], 3)])  # fmt: skip
    header = ["Chọn → áp", "Ngưỡng", "FPR thực tế", "Recall thực tế", "Recall@FPR5% trên chính tập"]
    lines += ["## Phép thử chuyển ngưỡng (FPR 5%)", "", *md_table(header, rows), ""]

    first = res["v3"][0]["cost_key"]
    rows = [
        [_p(r["policy"]), r["alerts"], r["tp"], r["fp"], fmt(r["recall"], 3),
         fmt(r["caught_amount"], 0), fmt(r["recall_amount"], 3), fmt(r["fpr"] * 100, 2) + "%"]
        for r in res["v3"] if r["cost_key"] == first and r["policy"] not in ("rule_raw",
                                                                              "rule_calibrated",
                                                                              "cost_v2")
    ]  # fmt: skip
    header = ["Chính sách", "Cảnh báo", "Gian lận bắt", "Báo nhầm", "Recall", "Tiền gian lận bắt",
              "Tỷ lệ tiền bắt", "FPR"]  # fmt: skip
    lines += ["## V3: chính sách không phụ thuộc chi phí", "", *md_table(header, rows), ""]

    rows = []
    for r in res["v3"]:
        rows.append([r["cost_key"], _p(r["policy"]), r["alerts"], r["tp"], r["fp"],
                     fmt(r["caught_amount"], 0), fmt(r["cost"], 0), _ci(r["cost_ci_day"]),
                     fmt(r["delta_vs_max_f1"], 0), _ci(r["delta_vs_max_f1_ci_day"]),
                     _ci(r["delta_vs_max_f1_ci_card1"])])  # fmt: skip
    header = ["Chi phí (L/R/F)", "Chính sách", "Cảnh báo", "Gian lận bắt", "Báo nhầm",
              "Tiền bắt", "Tổng chi phí", "CI theo ngày", "Chênh so với max F1",
              "CI chênh (ngày)", "CI chênh (card1)"]  # fmt: skip
    lines += ["## V3: toàn bộ lưới chi phí", "", *md_table(header, rows), ""]

    rows = []
    by_key = {(r["cost_key"], r["policy"]): r for r in res["v3"]}
    for key, best in res["v3_winners"].items():
        r = by_key[(key, best)]
        rows.append([key, _p(best), fmt(r["delta_vs_max_f1"], 0),
                     _ci(r["delta_vs_max_f1_ci_day"]), _ci(r["delta_vs_max_f1_ci_card1"])]
                    + [_p(w["winners"][key]) for w in res["rolling"]])  # fmt: skip
    header = ["Chi phí (L/R/F)", "Tốt nhất trên V3", "Chênh so với max F1", "CI (ngày)",
              "CI (card1)"] + [w["window"] for w in res["rolling"]]  # fmt: skip
    lines += ["## Chính sách có chi phí thấp nhất", "", *md_table(header, rows), ""]
    sc = res["self_checks"]
    pm = sc["permuted_v3"]
    lines += [
        "## Tự kiểm tra",
        "",
        f"- Ngưỡng chi phí chọn trên điểm đã hiệu chỉnh cho cùng cảnh báo với điểm gốc: "
        f"{sc['calibrated_v2_threshold_same_alerts']}.",
        f"- Hoán vị nhãn V3 ({pm['cost_key']}, {pm['policy']}): recall {fmt(pm['recall'], 3)}, "
        f"tỷ lệ cảnh báo {fmt(pm['alert_rate'], 3)} (ngẫu nhiên thì hai số bằng nhau).",
        "",
    ]
    return "\n".join(lines)


def load_policy_config(path: Path) -> tuple[PolicyConfig, dict[str, Any], str]:
    return _load(path, PolicyConfig)


def run(
    config_path: Path, *, data_dir: Path | None = None, manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
) -> Path:  # fmt: skip
    """Load and check the data, run G04, write `artifacts/experiments/pol-<hash>/`."""
    cfg, raw, text = load_policy_config(config_path)
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    dev = prepare(data.X, data.y, data.time, cfg)
    run_hash = experiment_hash(raw, cfg.seed, manifest.checksum, dev)
    run_id = run_id_from_hash(run_hash).replace("run-", "pol-")
    res = run_policy(dev, cfg)
    out = artifacts_dir / "experiments" / run_id
    write_common(out, text)
    write_json(out / "results.json", {"run_id": run_id, "run_hash": run_hash, **res})
    (out / "summary.md").write_text(summary_markdown(run_id, res), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Stage G decision policies (development data)")
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
