"""Stage B runner: rule-based and logistic baselines on IEEE-CIS.

    python -m fraud_risk.scripts.run_baseline --config CONFIG --stage validation
    python -m fraud_risk.scripts.run_baseline --config CONFIG --stage final [--force]

`validation` evaluates train and validation only. `final` also evaluates test, once per
frozen config hash (test-once rule, AGENTS.md section 8).
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd
from dataset_management.manifest import (
    ChecksumMismatchError,
    DatasetFileNotFoundError,
    load_manifest,
    verify_files,
)

from fraud_risk.adapters.ieee_cis import (
    DatasetNotFoundError,
    IeeeCisSchemaError,
    check_files,
    load_ieee_cis,
    required_files,
    resolve_data_dir,
)
from fraud_risk.baselines.logistic import LogisticBaseline
from fraud_risk.baselines.rule_based import RuleBasedBaseline, RuleConfigError
from fraud_risk.evaluation.metrics import evaluate, pr_auc, select_threshold, threshold_metrics
from fraud_risk.evaluation.run_log import (
    AlreadyEvaluatedOnTestError,
    check_test_once,
    compute_run_hash,
    register_test_run,
    run_id_from_hash,
    write_run,
)
from fraud_risk.evaluation.split import Split, SplitError, assert_no_time_overlap, time_split
from fraud_risk.features.baseline_features import (
    FeatureSpec,
    FeatureSpecError,
    LabelLeakError,
    build_features,
)
from fraud_risk.features.guards import check_label_leakage
from fraud_risk.scripts.config import BaselineConfig, ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[4]
ACCURACY_NOTE = (
    "Accuracy is not reported: with a few percent fraud, predicting 'never fraud' scores "
    "high accuracy. Use PR-AUC, precision/recall and FPR."
)


class ConfigNotFrozenError(RuntimeError):
    """`--stage final` needs a config the owner has set to `status: frozen`."""


def fit_baselines(
    X: pd.DataFrame, y: pd.Series, time: pd.Series, split: Split, cfg: BaselineConfig
) -> dict[str, Any]:
    """Fit both baselines on TRAIN rows and return scores for every partition.

    Rejects any split that is not chronological (the leaky `random_split` cannot be used).
    """
    assert_no_time_overlap(split, time)
    spec = FeatureSpec.from_config(cfg.features.model_dump())
    features = build_features(X, spec)
    check_label_leakage(features.loc[split.train], y.loc[split.train])

    rules = RuleBasedBaseline(cfg.rule_based.rules).fit(X.loc[split.train], y.loc[split.train])
    logistic = LogisticBaseline(
        spec.numeric_out,
        spec.categorical_out,
        seed=cfg.seed,
        C=cfg.logistic.C,
        max_iter=cfg.logistic.max_iter,
    ).fit(features.loc[split.train], y.loc[split.train])

    parts = {"train": split.train, "valid": split.valid, "test": split.test}
    return {
        "rule_based": {
            "model": rules,
            "scores": {name: rules.score(X.loc[idx]) for name, idx in parts.items()},
        },
        "logistic": {
            "model": logistic,
            "scores": {name: logistic.score(features.loc[idx]) for name, idx in parts.items()},
        },
    }


def run(
    config_path: Path,
    stage: str,
    *,
    data_dir: Path | None = None,
    manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
    force: bool = False,
) -> Path:
    """Run the baselines and write the run folder. Returns the folder path."""
    cfg, raw, text = load_config(config_path)
    if stage == "final" and cfg.status != "frozen":
        raise ConfigNotFrozenError(
            f"{config_path} has status '{cfg.status}'. Only the owner sets 'status: frozen' "
            "before the one-time test evaluation."
        )
    directory = resolve_data_dir(data_dir)
    check_files(directory, cfg.data.use_identity)
    manifest = load_manifest(manifest_path or Path(cfg.data.manifest))
    verify_files(manifest, directory, required_files(cfg.data.use_identity))

    data = load_ieee_cis(
        directory, use_identity=cfg.data.use_identity, parquet_dir=artifacts_dir / "parquet"
    )
    split = time_split(data.time, cfg.split.train_frac, cfg.split.valid_frac)
    run_hash = compute_run_hash(raw, cfg.seed, manifest.checksum, split.boundaries)
    run_id = run_id_from_hash(run_hash)
    registry = artifacts_dir / "test_runs.json"
    warnings = []
    if stage == "final" and (warning := check_test_once(registry, run_hash, force)):
        warnings.append(warning)

    fitted = fit_baselines(data.X, data.y, data.time, split, cfg)
    m = cfg.metrics
    y_parts = {"train": data.y.loc[split.train], "valid": data.y.loc[split.valid]}
    if stage == "final":
        y_parts["test"] = data.y.loc[split.test]

    metrics: dict[str, Any] = {
        "stage": stage,
        "run_id": run_id,
        "run_hash": run_hash,
        "note": ACCURACY_NOTE,
        "row_counts": data.row_counts,
        "warnings": warnings,
        "models": {},
    }
    thresholds: dict[str, Any] = {}
    for name, result in fitted.items():
        scores = result["scores"]
        threshold = select_threshold(
            y_parts["valid"], scores["valid"], m.threshold_method, m.precision_target
        )
        thresholds[name] = {
            "threshold": threshold,
            "method": m.threshold_method,
            "precision_target": m.precision_target,
            "chosen_on": "valid",
        }
        model_metrics = {
            "train": {
                "pr_auc": pr_auc(y_parts["train"], scores["train"]),
                "at_threshold": threshold_metrics(y_parts["train"], scores["train"], threshold),
            }
        }
        for part in [p for p in ("valid", "test") if p in y_parts]:
            model_metrics[part] = evaluate(
                y_parts[part],
                scores[part],
                threshold,
                precision_target=m.precision_target,
                fpr_target=m.fpr_target,
                n_resamples=m.bootstrap_resamples,
                seed=cfg.seed,
            )
        metrics["models"][name] = model_metrics

    run_dir = artifacts_dir / "runs" / run_id
    if stage == "final":
        run_dir = run_dir / "test"
    split_info = split.to_dict()
    split_info["fraud_rate"] = {
        "train": float(data.y.loc[split.train].mean()),
        "valid": float(data.y.loc[split.valid].mean()),
    }
    write_run(
        run_dir,
        config_text=text,
        metrics=metrics,
        split=split_info,
        thresholds=thresholds,
        manifest_checksum=manifest.checksum,
        models={
            "rule_based": {"rules": fitted["rule_based"]["model"].describe()},
            "logistic": fitted["logistic"]["model"].describe(),
        },
        repo_root=REPO_ROOT,
    )
    if stage == "final":
        register_test_run(registry, run_hash, run_id, forced=bool(warnings))
    return run_dir


KNOWN_ERRORS = (
    ConfigError,
    ConfigNotFrozenError,
    DatasetNotFoundError,
    DatasetFileNotFoundError,
    ChecksumMismatchError,
    IeeeCisSchemaError,
    SplitError,
    FeatureSpecError,
    LabelLeakError,
    RuleConfigError,
    AlreadyEvaluatedOnTestError,
)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Stage B fraud baselines")
    parser.add_argument("--config", type=Path, required=True)
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
