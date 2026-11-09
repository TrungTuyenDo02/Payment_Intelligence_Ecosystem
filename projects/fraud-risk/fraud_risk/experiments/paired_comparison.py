"""Open question 2: is a Gradient Boosting variant really better than the baseline, on validation?

Two runs are compared on the SAME validation rows with a paired bootstrap, which is much tighter
than comparing two separate confidence intervals. Each run's model is refitted on train with the
parameters it chose (from its `models.json`); the refitted validation PR-AUC must equal the logged
one, so a drift in code or data is caught. Test rows are never scored.

Several candidates against one baseline is a multiple-comparison setting: the best of k noisy
differences looks better than it is, so read the intervals, not the single best number.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dataset_management.manifest import DatasetFileNotFoundError

from fraud_risk.evaluation.metrics import pr_auc, recall_at_fpr
from fraud_risk.evaluation.run_log import write_json
from fraud_risk.evaluation.split import time_split
from fraud_risk.experiments.split_diagnostics import paired_bootstrap_diff
from fraud_risk.features.baseline_features import FeatureSpec, build_features
from fraud_risk.models.gbm import GbmModel
from fraud_risk.scripts.config import load_gbm_config
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data

MODEL_PARAMS = ("learning_rate", "max_iter", "max_leaf_nodes")


class ReproductionError(RuntimeError):
    """A refitted model does not reproduce the validation score logged by its run."""


def _refit_valid_scores(
    run_dir: Path, data: Any, tolerance: float = 1e-6
) -> tuple[Any, np.ndarray]:
    """Refit the run's chosen model on train; return (config, validation scores)."""
    cfg, _, _ = load_gbm_config(run_dir / "config.yaml")
    chosen = json.loads((run_dir / "models.json").read_text("utf-8"))["gbm"]["params"]
    params = {k: chosen[k] for k in MODEL_PARAMS}
    split = time_split(data.time, cfg.split.train_frac, cfg.split.valid_frac, cfg.split.gap_days)
    spec = FeatureSpec.from_config(cfg.features.model_dump())
    features = build_features(data.X, spec)
    model = GbmModel(spec.numeric_out, spec.categorical_out, seed=cfg.seed, params=params)
    model.fit(features.loc[split.train], data.y.loc[split.train])
    scores = model.score(features.loc[split.valid])
    logged = json.loads((run_dir / "metrics.json").read_text("utf-8"))["models"]["gbm"]["valid"]
    refit = pr_auc(data.y.loc[split.valid], scores)
    if abs(refit - logged["pr_auc"]) > tolerance:
        raise ReproductionError(f"{run_dir.name}: refit {refit} vs logged {logged['pr_auc']}")
    return cfg, scores


def compare(
    base_run: Path, candidate_runs: list[Path], data: Any, *, n_resamples: int = 500
) -> dict[str, Any]:
    """Paired bootstrap of PR-AUC and recall at FPR: candidate minus baseline, per candidate."""
    cfg, base_scores = _refit_valid_scores(base_run, data)
    split = time_split(data.time, cfg.split.train_frac, cfg.split.valid_frac, cfg.split.gap_days)
    y: pd.Series = data.y.loc[split.valid]
    fpr = cfg.metrics.fpr_target

    def recall(yt: np.ndarray, s: np.ndarray) -> float:
        return float(recall_at_fpr(yt, s, fpr)["recall"])

    out: dict[str, Any] = {}
    for run_dir in candidate_runs:
        other_cfg, scores = _refit_valid_scores(run_dir, data)
        if other_cfg.split != cfg.split or other_cfg.seed != cfg.seed:
            raise ValueError(f"{run_dir.name} uses a different split or seed than the baseline")
        kw = {"n_resamples": n_resamples, "seed": cfg.seed}
        out[run_dir.name] = {
            "pr_auc_diff": paired_bootstrap_diff(y, scores, base_scores, **kw),
            "recall_at_fpr_diff": paired_bootstrap_diff(
                y, scores, base_scores, metric=recall, **kw
            ),
        }
    return {"baseline": base_run.name, "validation_rows": int(len(y)), "candidates": out,
            "n_resamples": n_resamples, "evaluated_on": "valid"}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Paired comparison of GBM runs (validation)")
    parser.add_argument("--base", type=Path, required=True, help="baseline run folder")
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True, help="JSON file to write")
    parser.add_argument("--resamples", type=int, default=500)
    args = parser.parse_args(argv)
    try:
        cfg, _, _ = load_gbm_config(args.base / "config.yaml")
        data, _ = load_checked_data(cfg.data, None, None, Path("artifacts"))
        result = compare(args.base, args.candidate, data, n_resamples=args.resamples)
    except DatasetFileNotFoundError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    except (*KNOWN_ERRORS, ReproductionError, ValueError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    write_json(args.out, result)
    print(json.dumps({"written": str(args.out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
