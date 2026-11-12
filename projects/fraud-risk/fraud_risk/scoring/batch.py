"""Stage G / G08: score a table of transactions in one batch (`make score-model`, `make score`).

EXPLORATORY: the model and calibrator are fitted on development data only (train; V1 for the
calibrator). This is a demo of how scores would be produced, not a production service.

Two steps:

1. `train`: fit the fixed GBM on train (same code path as Stage G, which checks it reproduces the
   Stage E validation PR-AUC), fit the calibrator on V1, and save `artifacts/models/score-<id>/`
   with the scorer, a model card, the training-time scores of validation rows (`dev_scores.csv`)
   and a label-free demo input taken from V3 (`sample_v3.csv`).
2. `score`: read a transaction CSV with the same reader and dtypes as training, build the same
   features, and write `artifacts/scores/<execution_id>.csv` (+ `.json` summary). Rows that were
   also scored at training time are compared (training-serving skew check).

Guards: the input must not contain the label; rows after the last validation time (the held-out
test period) are refused; only row-local features are allowed, because history features would
need earlier rows of each entity that a batch does not carry.

`scorer.pkl` is a pickle: load it only from an `artifacts/models/` folder this code wrote.
"""

import argparse
import hashlib
import json
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from dataset_management.manifest import DatasetFileNotFoundError

from fraud_risk.adapters.ieee_cis import ID, LABEL, TIME, read_transactions
from fraud_risk.evaluation.run_log import (
    compute_run_hash,
    environment_text,
    execution_id,
    git_sha,
    utc_now,
    write_execution,
    write_json,
)
from fraud_risk.experiments.calibration import Calibrator, fit_calibrator
from fraud_risk.experiments.decision_data import DevData, ReproductionError, blocks, prepare
from fraud_risk.features.baseline_features import (
    FEATURES_VERSION,
    ROW_LOCAL_DERIVED,
    FeatureSpec,
    LabelLeakError,
    build_features,
)
from fraud_risk.models.gbm import GbmModel
from fraud_risk.scripts.config import ScoringConfig, _load
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "scoring.yaml"
NOTE = (
    "Exploratory (thăm dò): model fitted on train, calibrator on V1 (development data only). "
    "Scores are a demo of batch scoring, not an operational fraud estimate."
)


class ScoringError(ValueError):
    """The scorer cannot be built, or the input table cannot be scored."""


class TestPeriodError(ScoringError):
    """The input has rows from the held-out test period (after the last validation time)."""

    __test__ = False  # not a pytest class


@dataclass(frozen=True)
class Scorer:
    """Everything needed to score a batch the same way as at training time."""

    model: GbmModel
    spec: FeatureSpec
    calibrator: Calibrator
    model_version: str
    feature_version: str
    last_dev_time: int  # last validation TransactionDT; later rows belong to the test period


def feature_version(spec: FeatureSpec) -> str:
    """`feat-v<FEATURES_VERSION>-` + 8 hex of the feature list (code version + configuration)."""
    payload = json.dumps(
        [spec.numeric, spec.categorical, spec.derived], separators=(",", ":"), sort_keys=True
    )
    return f"feat-v{FEATURES_VERSION}-" + hashlib.sha256(payload.encode()).hexdigest()[:8]


def build_scorer(dev: DevData, cfg: ScoringConfig, model_version: str) -> Scorer:
    """Wrap the GBM fitted by `prepare` and a calibrator fitted on V1 (role-checked)."""
    spec = FeatureSpec.from_config(cfg.features.model_dump())
    if history := sorted(set(spec.derived) - ROW_LOCAL_DERIVED):
        raise ScoringError(f"batch scoring supports row-local features only, not {history}")
    if dev.fitted_gbm is None:
        raise ScoringError("development data has no fitted GBM")
    calibrator = fit_calibrator(cfg.scoring.calibration, dev, "gbm", blocks(dev)["V1"])
    if not calibrator.monotone:
        raise ScoringError(f"calibrator {calibrator.params} is not increasing")
    return Scorer(
        model=dev.fitted_gbm,
        spec=spec,
        calibrator=calibrator,
        model_version=model_version,
        feature_version=feature_version(spec),
        last_dev_time=int(dev.split_boundaries["valid"]["max_time"]),
    )


def score_batch(scorer: Scorer, transactions: pd.DataFrame, exec_id: str) -> pd.DataFrame:
    """Scores per input row, in input order. Raises on label, bad IDs or test-period rows."""
    if LABEL in transactions.columns:
        raise LabelLeakError(f"input must not contain the label column '{LABEL}'")
    for column in (ID, TIME):
        if column not in transactions.columns:
            raise ScoringError(f"input is missing the column '{column}'")
    if transactions[ID].duplicated().any():
        raise ScoringError(f"duplicate {ID} values in the input")
    late = int((transactions[TIME] > scorer.last_dev_time).sum())
    if late:
        raise TestPeriodError(
            f"{late} row(s) after TransactionDT {scorer.last_dev_time}: that is the held-out "
            "test period, which this scorer must not read (test-once rule)"
        )
    features = build_features(transactions.set_index(ID), scorer.spec)
    raw = scorer.model.score(features)
    return pd.DataFrame(
        {
            ID: transactions[ID].to_numpy(),
            "score": raw,
            "score_calibrated": scorer.calibrator.apply(raw),
            "model_version": scorer.model_version,
            "feature_version": scorer.feature_version,
            "execution_id": exec_id,
        }
    )


# --- train / score commands --------------------------------------------------------------------


def latest_model_dir(artifacts_dir: Path) -> Path:
    """Folder of the last trained scorer (`artifacts/models/LATEST`)."""
    pointer = artifacts_dir / "models" / "LATEST"
    if not pointer.is_file():
        raise ScoringError(f"no trained scorer in {artifacts_dir / 'models'}: run make score-model")
    return artifacts_dir / "models" / pointer.read_text("utf-8").strip()


def train(
    config_path: Path, *, data_dir: Path | None = None, manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
) -> Path:  # fmt: skip
    """Fit and save the scorer; returns `artifacts/models/score-<id>/`."""
    started = utc_now()
    cfg, raw, text = _load(config_path, ScoringConfig)
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    dev = prepare(data.X, data.y, data.time, cfg)  # drops test rows first
    bounds = {**dev.split_boundaries, "blocks": raw["blocks"]}
    model_version = "score-" + compute_run_hash(raw, cfg.seed, manifest.checksum, bounds)[:12]
    scorer = build_scorer(dev, cfg, model_version)

    out = artifacts_dir / "models" / model_version
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(text, encoding="utf-8")
    (out / "environment.txt").write_text(environment_text(), encoding="utf-8")
    (out / "git_sha.txt").write_text(git_sha(REPO_ROOT) + "\n", encoding="utf-8")
    with (out / "scorer.pkl").open("wb") as fh:
        pickle.dump(scorer, fh, protocol=pickle.HIGHEST_PROTOCOL)
    valid = dev.frame.loc[dev.valid].sort_values(["time"], kind="stable")
    valid[["score_gbm"]].rename(columns={"score_gbm": "score"}).rename_axis(ID).to_csv(
        out / "dev_scores.csv"
    )
    v3 = valid.index[valid["block"] == "V3"][: cfg.scoring.sample_rows]
    data.X.loc[v3].copy().rename_axis(ID).reset_index().to_csv(out / "sample_v3.csv", index=False)
    write_json(
        out / "model_card.json",
        {
            "note": NOTE,
            "model_version": model_version,
            "feature_version": scorer.feature_version,
            "features": {"numeric": list(scorer.spec.numeric_out),
                         "categorical": list(scorer.spec.categorical_out)},
            "model": dev.models["gbm"],
            "calibration": {"method": scorer.calibrator.method,
                            "params": scorer.calibrator.params, "fitted_on": "V1"},
            "train_rows": len(dev.train),
            "train_prevalence": dev.train_prevalence,
            "last_dev_time": scorer.last_dev_time,
            "split_boundaries": {k: v for k, v in dev.split_boundaries.items() if k != "test"},
            "sample_rows": len(v3),
        },
    )  # fmt: skip
    write_execution(out, model_version, started, REPO_ROOT)
    (artifacts_dir / "models" / "LATEST").write_text(model_version + "\n", encoding="utf-8")
    return out


def score_file(
    model_dir: Path, input_path: Path, *, artifacts_dir: Path = Path("artifacts"),
    output: Path | None = None,
) -> Path:  # fmt: skip
    """Score one CSV; write `<execution_id>.csv` and a `.json` summary; return the CSV path."""
    started = utc_now()
    with (model_dir / "scorer.pkl").open("rb") as fh:
        scorer: Scorer = pickle.load(fh)  # noqa: S301 - our own artifact, see module docstring
    transactions = read_transactions(input_path)
    eid = execution_id(scorer.model_version, started, git_sha(REPO_ROOT), environment_text())
    scored = score_batch(scorer, transactions, eid)

    known = pd.read_csv(model_dir / "dev_scores.csv", index_col=ID)["score"]
    both = scored.set_index(ID)["score"].loc[lambda s: s.index.isin(known.index)]
    diff = (both - known.loc[both.index]).abs()
    output = output or artifacts_dir / "scores" / f"{eid}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    scored.to_csv(output, index=False)
    write_json(
        output.with_suffix(".json"),
        {
            "note": NOTE,
            "execution_id": eid,
            "model_version": scorer.model_version,
            "feature_version": scorer.feature_version,
            "input": str(input_path),
            "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
            "rows": len(scored),
            "started_at": started.isoformat(),
            "commit": git_sha(REPO_ROOT),
            "score_mean": float(scored["score"].mean()) if len(scored) else None,
            "score_calibrated_mean": (
                float(scored["score_calibrated"].mean()) if len(scored) else None
            ),
            "skew_check": {
                "rows_compared": len(both),
                "max_abs_diff": float(diff.max()) if len(both) else None,
            },
        },
    )
    return output


def main(argv: list[str] | None = None) -> int:
    """CLI: `train` or `score`; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="G08 batch scorer (development data only)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_train = sub.add_parser("train", help="fit and save the scorer")
    p_train.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p_train.add_argument("--data-dir", type=Path, default=None)
    p_train.add_argument("--manifest", type=Path, default=None)
    p_score = sub.add_parser("score", help="score a transaction CSV")
    p_score.add_argument("--model-dir", type=Path, default=None, help="default: latest")
    p_score.add_argument("--input", type=Path, default=None, help="default: sample_v3.csv")
    p_score.add_argument("--output", type=Path, default=None)
    for p in (p_train, p_score):
        p.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    try:
        if args.command == "train":
            out = train(args.config, data_dir=args.data_dir, manifest_path=args.manifest,
                        artifacts_dir=args.artifacts_dir)  # fmt: skip
            print(json.dumps({"model folder": str(out)}))
            return 0
        model_dir = args.model_dir or latest_model_dir(args.artifacts_dir)
        input_path = args.input or model_dir / "sample_v3.csv"
        out = score_file(model_dir, input_path, artifacts_dir=args.artifacts_dir,
                         output=args.output)  # fmt: skip
        summary = json.loads(out.with_suffix(".json").read_text("utf-8"))
        keys = ("execution_id", "model_version", "rows", "skew_check")
        print(json.dumps({"scores": str(out), **{k: summary[k] for k in keys}}))
        return 0
    except (DatasetFileNotFoundError, FileNotFoundError, ScoringError, LabelLeakError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    except (*KNOWN_ERRORS, ReproductionError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
