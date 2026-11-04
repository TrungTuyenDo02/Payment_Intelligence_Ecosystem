"""Stage E runner: Gradient Boosting on IEEE-CIS (`make gbm`, `make gbm-final`).

    python -m fraud_risk.scripts.run_gbm --config CONFIG --stage validation
    python -m fraud_risk.scripts.run_gbm --config CONFIG --stage final [--force]

Every grid point is fitted on TRAIN and scored on validation; the best validation PR-AUC wins and
its threshold is chosen on validation. `final` scores test with that same fitted model, once per
frozen config hash (same registry as Stage B, `artifacts/test_runs.json`).
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from dataset_management.manifest import DatasetFileNotFoundError

from fraud_risk.evaluation.metrics import evaluate, pr_auc, select_threshold, threshold_metrics
from fraud_risk.evaluation.run_log import (
    check_test_once,
    compute_run_hash,
    register_test_run,
    run_id_from_hash,
    write_run,
)
from fraud_risk.evaluation.split import assert_no_time_overlap, time_split
from fraud_risk.features.baseline_features import FeatureSpec, build_features
from fraud_risk.features.guards import check_label_leakage
from fraud_risk.models.gbm import GbmModel, param_grid
from fraud_risk.scripts.config import load_gbm_config
from fraud_risk.scripts.run_baseline import (
    ACCURACY_NOTE,
    KNOWN_ERRORS,
    REPO_ROOT,
    ConfigNotFrozenError,
    load_checked_data,
)

DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "gbm.yaml"


def run(
    config_path: Path,
    stage: str,
    *,
    data_dir: Path | None = None,
    manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
    force: bool = False,
) -> Path:
    """Fit the grid on train, pick on validation, write the run folder. Returns its path."""
    cfg, raw, text = load_gbm_config(config_path)
    if stage == "final" and cfg.status != "frozen":
        raise ConfigNotFrozenError(
            f"{config_path} has status '{cfg.status}'. Only the owner sets 'status: frozen' "
            "before the one-time test evaluation."
        )
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    split = time_split(data.time, cfg.split.train_frac, cfg.split.valid_frac, cfg.split.gap_days)
    assert_no_time_overlap(split, data.time)
    run_hash = compute_run_hash(raw, cfg.seed, manifest.checksum, split.boundaries)
    run_id = run_id_from_hash(run_hash)
    registry = artifacts_dir / "test_runs.json"
    warnings = []
    if stage == "final" and (warning := check_test_once(registry, run_hash, force)):
        warnings.append(warning)

    spec = FeatureSpec.from_config(cfg.features.model_dump())
    features = build_features(data.X, spec)
    check_label_leakage(features.loc[split.train], data.y.loc[split.train])
    y_train, y_valid = data.y.loc[split.train], data.y.loc[split.valid]

    grid_results: list[dict[str, Any]] = []
    best: tuple[float, GbmModel] | None = None
    for params in param_grid(cfg.gbm.grid):
        model = GbmModel(spec.numeric_out, spec.categorical_out, seed=cfg.seed, params=params)
        model.fit(features.loc[split.train], y_train)
        valid_ap = pr_auc(y_valid, model.score(features.loc[split.valid]))
        grid_results.append({"params": params, "valid_pr_auc": valid_ap})
        if best is None or valid_ap > best[0]:  # ties keep the earlier (fixed order) point
            best = (valid_ap, model)
    assert best is not None
    model = best[1]

    m = cfg.metrics
    scores = {"train": model.score(features.loc[split.train]),
              "valid": model.score(features.loc[split.valid])}  # fmt: skip
    threshold = select_threshold(y_valid, scores["valid"], m.threshold_method, m.precision_target)
    model_metrics: dict[str, Any] = {
        "train": {
            "pr_auc": pr_auc(y_train, scores["train"]),
            "at_threshold": threshold_metrics(y_train, scores["train"], threshold),
        }
    }
    parts = {"valid": y_valid}
    if stage == "final":
        scores["test"] = model.score(features.loc[split.test])
        parts["test"] = data.y.loc[split.test]
    for part, y_part in parts.items():
        model_metrics[part] = evaluate(
            y_part, scores[part], threshold, precision_target=m.precision_target,
            fpr_target=m.fpr_target, n_resamples=m.bootstrap_resamples, seed=cfg.seed,
        )  # fmt: skip

    metrics = {
        "stage": stage,
        "run_id": run_id,
        "run_hash": run_hash,
        "note": ACCURACY_NOTE,
        "row_counts": data.row_counts,
        "warnings": warnings,
        "models": {"gbm": model_metrics},
    }
    run_dir = artifacts_dir / "runs" / run_id
    if stage == "final":
        run_dir = run_dir / "test"
    split_info = split.to_dict()
    split_info["fraud_rate"] = {"train": float(y_train.mean()), "valid": float(y_valid.mean())}
    write_run(
        run_dir,
        config_text=text,
        metrics=metrics,
        split=split_info,
        thresholds={"gbm": {"threshold": threshold, "method": m.threshold_method,
                            "precision_target": m.precision_target, "chosen_on": "valid"}},
        manifest_checksum=manifest.checksum,
        models={"gbm": {**model.describe(), "grid": grid_results, "chosen_on": "valid"}},
        repo_root=REPO_ROOT,
    )  # fmt: skip
    if stage == "final":
        register_test_run(registry, run_hash, run_id, forced=bool(warnings))
    return run_dir


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Stage E Gradient Boosting")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--stage", choices=["validation", "final"], default="validation")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--force", action="store_true", help="final only; logged as a warning")
    args = parser.parse_args(argv)
    try:
        run_dir = run(
            args.config,
            args.stage,
            data_dir=args.data_dir,
            manifest_path=args.manifest,
            artifacts_dir=args.artifacts_dir,
            force=args.force,
        )
    except DatasetFileNotFoundError as err:
        print(
            f"ERROR: {err}\nCreate the manifest first: see shared/dataset-management/README.md",
            file=sys.stderr,
        )
        return 2
    except KNOWN_ERRORS as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    print(f"run folder: {run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
