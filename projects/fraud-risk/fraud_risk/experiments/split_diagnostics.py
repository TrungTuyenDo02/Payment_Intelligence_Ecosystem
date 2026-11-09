"""Open question 1: why does a random split score LOWER than a time split?

Leakage experiment `leak-827d929eaa73` showed PR-AUC 0.177 (random) vs 0.245 (time) for the same
Logistic Regression. The two validation sets are not the same rows: the random one covers all six
months, the time one only the weeks after train. This script separates the causes.

Only the first `train_frac + valid_frac` of the rows by time (train + validation of the frozen
split) are used. Test rows are never scored and their labels are never read.

| step | what it does                                                                        |
| ---- | ----------------------------------------------------------------------------------- |
| 1.1  | 2x2: models trained on {time, random} train, scored on {time, random} validation    |
| 1.2  | PR-AUC re-weighted to one common fraud prevalence (exact, no resampling)            |
| 1.3  | weekly prevalence, PR-AUC and recall at FPR, for both validation sets               |
| 1.4  | share of validation rows whose `card1` was seen in train, per split                 |
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dataset_management.manifest import DatasetFileNotFoundError
from sklearn.metrics import average_precision_score

from fraud_risk.baselines.logistic import LogisticBaseline
from fraud_risk.evaluation.entity_overlap import entity_overlap
from fraud_risk.evaluation.metrics import pr_auc, recall_at_fpr
from fraud_risk.evaluation.run_log import compute_run_hash, git_sha, run_id_from_hash, write_json
from fraud_risk.evaluation.split import Split, random_split, time_split
from fraud_risk.features.baseline_features import FeatureSpec, build_features
from fraud_risk.scripts.config import LeakageConfig, load_leakage_config
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "leakage.yaml"
WEEK_SECONDS = 7 * 24 * 3600


def reweighted_pr_auc(y: pd.Series, scores: np.ndarray, prevalence: float) -> float:
    """Average precision as if the fraud rate were `prevalence`: positives get a common weight."""
    p = float(y.mean())
    weight = (prevalence / (1 - prevalence)) * ((1 - p) / p)
    return float(average_precision_score(y, scores, sample_weight=np.where(y == 1, weight, 1.0)))


def _score(
    y: pd.Series, scores: np.ndarray, fpr_target: float, prevalence: float
) -> dict[str, Any]:
    return {
        "rows": int(len(y)),
        "prevalence": float(y.mean()),
        "pr_auc": pr_auc(y, scores),
        "pr_auc_at_common_prevalence": reweighted_pr_auc(y, scores, prevalence),
        "recall_at_fpr": recall_at_fpr(y, scores, fpr_target)["recall"],
    }


def run_diagnostics(
    X: pd.DataFrame, y: pd.Series, time: pd.Series, cfg: LeakageConfig
) -> dict[str, Any]:
    """Steps 1.1 to 1.4. Pure: writes nothing and never touches test rows."""
    spec = FeatureSpec.from_config(cfg.features.model_dump())
    features = build_features(X, spec)
    num, cat = spec.numeric_out, spec.categorical_out
    s = cfg.split
    frozen = time_split(time, s.train_frac, s.valid_frac)
    pre = frozen.train.append(frozen.valid)  # train + validation rows only; test stays untouched
    share = s.train_frac / (s.train_frac + s.valid_frac)
    # random_split needs fractions summing below 1; the 1e-9 leaves no test rows after rounding.
    rand = random_split(pre, share, 1 - share - 1e-9, seed=cfg.seed)
    splits = {
        "time": (frozen.train, frozen.valid),
        "random": (rand.train, rand.valid),
    }
    fpr = cfg.metrics.fpr_target
    common = float(y.loc[frozen.valid].mean())  # the time validation fraud rate

    models = {
        name: LogisticBaseline(num, cat, seed=cfg.seed, C=cfg.logistic.C,
                               max_iter=cfg.logistic.max_iter)
        .fit(features.loc[train], y.loc[train])
        for name, (train, _) in splits.items()
    }  # fmt: skip
    matrix: dict[str, dict[str, Any]] = {}
    for m_name, model in models.items():
        for v_name, (_, valid) in splits.items():
            scores = model.score(features.loc[valid])
            matrix[f"train_{m_name}__valid_{v_name}"] = _score(y.loc[valid], scores, fpr, common)

    # Same rows for both models: random-validation rows that fall in the time-validation period.
    window = rand.valid[time.loc[rand.valid] >= time.loc[frozen.valid].min()]
    same_rows = {
        f"train_{name}": _score(y.loc[window], model.score(features.loc[window]), fpr, common)
        for name, model in models.items()
    }

    def weekly(model: LogisticBaseline, rows_all: pd.Index) -> list[dict[str, Any]]:
        week = (time.loc[rows_all] // WEEK_SECONDS).astype(int)
        scores = pd.Series(model.score(features.loc[rows_all]), index=rows_all)
        out = []
        for w in sorted(week.unique()):
            rows = week.index[week == w]
            yw = y.loc[rows]
            entry: dict[str, Any] = {
                "week": int(w), "rows": int(len(rows)), "prevalence": float(yw.mean())
            }  # fmt: skip
            if 0 < yw.sum() < len(yw):
                entry["pr_auc"] = pr_auc(yw, scores.loc[rows])
                entry["recall_at_fpr"] = recall_at_fpr(yw, scores.loc[rows], fpr)["recall"]
            out.append(entry)
        return out

    overlap = {
        name: entity_overlap(X, y, Split(name, train, valid_idx, pd.Index([]), {}), [["card1"]])[0][
            "share_seen_in_train"
        ]
        for name, (train, valid_idx) in splits.items()
    }
    return {
        "common_prevalence": common,
        "pre_test_rows": int(len(pre)),
        "matrix": matrix,
        "same_rows_in_time_valid_period": {"rows": int(len(window)), "scores": same_rows},
        "weekly_time_valid": weekly(models["time"], frozen.valid),
        "weekly_random_valid": weekly(models["random"], rand.valid),
        "card1_seen_share": overlap,
        "split_boundaries": frozen.boundaries,
        "evaluated_on": "train+valid only",
    }


def run(
    config_path: Path, *, data_dir: Path | None = None, manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
) -> Path:  # fmt: skip
    """Load and check the data, run the diagnostics, write the experiment folder."""
    cfg, raw, _ = load_leakage_config(config_path)
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    result = run_diagnostics(data.X, data.y, data.time, cfg)
    run_hash = compute_run_hash(raw, cfg.seed, manifest.checksum, result["split_boundaries"])
    run_id = run_id_from_hash(run_hash).replace("run-", "diag-")
    out = artifacts_dir / "experiments" / run_id
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "results.json", {"run_id": run_id, "run_hash": run_hash, **result})
    (out / "git_sha.txt").write_text(git_sha(REPO_ROOT) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Random vs time split diagnostics (validation)")
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
    except KNOWN_ERRORS as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    print(json.dumps({"experiment folder": str(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
