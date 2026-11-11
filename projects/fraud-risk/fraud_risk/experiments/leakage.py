"""Stage E leakage experiment (`make leakage`): what each shortcut does to the validation score.

Every variant breaks exactly one rule of Stage B, or adds a label-delay gap (ADR 0003), and is
scored on VALIDATION only. Test rows are never scored and test labels are never read.

| variant                | what changes                                                    |
| ---------------------- | --------------------------------------------------------------- |
| `proper`               | the frozen Stage B Logistic Regression setup                    |
| `random_split`         | rows shuffled before the 60/20/20 split (rule 7)                |
| `preprocess_on_all`    | imputer, scaler, encoder fitted on all rows' features (rule 8)  |
| `target_enc_train`     | + card1 target encoding from train labels, out-of-fold on train |
| `target_enc_leaky`     | + card1 target encoding fitted on train AND validation labels   |
| `gap_<n>d`             | last n days of train dropped (label delay, ADR 0003)            |

The model is the baseline Logistic Regression throughout, so only the shortcut differs.
Leakage taxonomy: Kapoor and Narayanan (2023); definitions: Kaufman et al. (2012).
"""

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dataset_management.manifest import DatasetFileNotFoundError

from fraud_risk.baselines.logistic import LogisticBaseline
from fraud_risk.evaluation.entity_overlap import entity_overlap
from fraud_risk.evaluation.metrics import bootstrap_pr_auc_ci, pr_auc, recall_at_fpr
from fraud_risk.evaluation.run_log import (
    compute_run_hash,
    environment_text,
    git_sha,
    run_id_from_hash,
    utc_now,
    write_execution,
    write_json,
)
from fraud_risk.evaluation.split import Split, random_split, time_split
from fraud_risk.features.baseline_features import FeatureSpec, build_features
from fraud_risk.features.target_encoding import TargetEncoder, encode_out_of_fold
from fraud_risk.scripts.config import LeakageConfig, load_leakage_config
from fraud_risk.scripts.run_baseline import KNOWN_ERRORS, load_checked_data

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = REPO_ROOT / "projects" / "fraud-risk" / "configs" / "leakage.yaml"
TE_FEATURE = "target_enc"


def _score_valid(y: pd.Series, scores: np.ndarray, cfg: LeakageConfig) -> dict[str, Any]:
    m = cfg.metrics
    return {
        "rows": int(len(y)),
        "prevalence": float(y.mean()),
        "pr_auc": pr_auc(y, scores),
        "pr_auc_ci": bootstrap_pr_auc_ci(
            y, scores, n_resamples=m.bootstrap_resamples, seed=cfg.seed
        ),  # fmt: skip
        "recall_at_fpr": recall_at_fpr(y, scores, m.fpr_target),
    }


def _logistic(spec_num: list[str], spec_cat: list[str], cfg: LeakageConfig) -> LogisticBaseline:
    return LogisticBaseline(spec_num, spec_cat, seed=cfg.seed, C=cfg.logistic.C,
                            max_iter=cfg.logistic.max_iter)  # fmt: skip


def _fit_and_score(
    features: pd.DataFrame, y: pd.Series, split: Split, cfg: LeakageConfig,
    numeric: list[str], categorical: list[str],
) -> dict[str, Any]:  # fmt: skip
    model = _logistic(numeric, categorical, cfg).fit(features.loc[split.train], y.loc[split.train])
    return _score_valid(y.loc[split.valid], model.score(features.loc[split.valid]), cfg)


def run_experiment(
    X: pd.DataFrame, y: pd.Series, time: pd.Series, cfg: LeakageConfig
) -> dict[str, Any]:
    """All variants, each scored on its own validation rows. Pure: writes nothing."""
    spec = FeatureSpec.from_config(cfg.features.model_dump())
    features = build_features(X, spec)
    num, cat = spec.numeric_out, spec.categorical_out
    s = cfg.split
    split = time_split(time, s.train_frac, s.valid_frac)
    variants: dict[str, dict[str, Any]] = {}

    variants["proper"] = _fit_and_score(features, y, split, cfg, num, cat)

    shuffled = random_split(X.index, s.train_frac, s.valid_frac, seed=cfg.seed)
    variants["random_split"] = _fit_and_score(features, y, shuffled, cfg, num, cat)

    # Preprocessing statistics from every row (features only, no labels), model on train rows.
    lr = _logistic(num, cat, cfg)
    pipeline = lr.build_pipeline()
    prep, model = pipeline.named_steps["prep"], pipeline.named_steps["model"]
    prep.fit(features[num + cat])
    model.fit(prep.transform(features.loc[split.train, num + cat]), y.loc[split.train])
    valid_scores = model.predict_proba(prep.transform(features.loc[split.valid, num + cat]))[:, 1]
    variants["preprocess_on_all"] = _score_valid(y.loc[split.valid], valid_scores, cfg)

    # Legitimate: train rows out-of-fold, other rows with an encoder fitted on all train labels.
    te = cfg.target_encoding
    column = X[te.column]
    encoded = TargetEncoder(te.smoothing).fit(column.loc[split.train], y.loc[split.train])
    legit = encoded.transform(column)
    legit.loc[split.train] = encode_out_of_fold(
        column.loc[split.train], y.loc[split.train], time, smoothing=te.smoothing
    )
    # Leaky: one encoder fitted on train AND validation labels, applied in-sample.
    rows = split.train.append(split.valid)
    leaky = TargetEncoder(te.smoothing).fit(column.loc[rows], y.loc[rows]).transform(column)
    for name, values in (("target_enc_train", legit), ("target_enc_leaky", leaky)):
        with_te = features.assign(**{TE_FEATURE: values})
        variants[name] = _fit_and_score(with_te, y, split, cfg, [*num, TE_FEATURE], cat)

    for gap in cfg.gap_days:
        gapped = time_split(time, s.train_frac, s.valid_frac, gap_days=gap)
        result = _fit_and_score(features, y, gapped, cfg, num, cat)
        result["train_rows"] = int(len(gapped.train))
        variants[f"gap_{gap:g}d"] = result

    base = variants["proper"]["pr_auc"]
    for result in variants.values():
        result["pr_auc_minus_proper"] = result["pr_auc"] - base
    return {
        "variants": variants,
        "entity_overlap": entity_overlap(X, y, split, cfg.entity_overlap.keys),
        "split_boundaries": split.boundaries,
        "evaluated_on": "valid",
    }


VARIANT_VN = {
    "proper": "Đúng quy tắc (baseline Stage B)",
    "random_split": "Chia ngẫu nhiên thay vì theo thời gian",
    "preprocess_on_all": "Fit tiền xử lý trên mọi dòng",
    "target_enc_train": "Thêm mã hoá card1 bằng nhãn train",
    "target_enc_leaky": "Mã hoá card1 bằng nhãn train + validation",
}


def summary_markdown(result: dict[str, Any], run_id: str) -> str:
    """Two tables (variants, entity overlap) in Vietnamese number format, for the report."""

    def vn(x: float | None, d: int = 3) -> str:
        if x is None:
            return "—"
        return f"{x:,.{d}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")

    lines = [f"Lần chạy `{run_id}` (chỉ đánh giá trên validation)", "",
             "| Biến thể | PR-AUC [95% CI] | Chênh so với đúng quy tắc | Recall @ FPR |",
             "| --- | --- | --- | --- |"]  # fmt: skip
    for name, v in result["variants"].items():
        label = VARIANT_VN.get(name, f"Khoảng trống {name[4:-1]} ngày trước validation")
        ci = v["pr_auc_ci"]
        lines.append(
            f"| {label} | {vn(v['pr_auc'])} [{vn(ci['low'])}; {vn(ci['high'])}] "
            f"| {'+' if v['pr_auc_minus_proper'] >= 0 else ''}{vn(v['pr_auc_minus_proper'])} "
            f"| {vn(v['recall_at_fpr']['recall'], 2)} |"
        )
    lines += ["", "| Định danh | Tập | Tỷ lệ dòng có định danh đã gặp trong train | "
              "Tỷ lệ gian lận: đã gặp / mới |", "| --- | --- | --- | --- |"]  # fmt: skip
    for row in result["entity_overlap"]:
        rates = (f"{vn(row['fraud_rate_seen'])} / {vn(row['fraud_rate_new'])}"
                 if row["part"] == "valid" else "không đọc nhãn test")  # fmt: skip
        part = "Validation" if row["part"] == "valid" else "Test"
        lines.append(f"| `{row['key']}` | {part} | {vn(row['share_seen_in_train'])} | {rates} |")
    return "\n".join(lines) + "\n"


def run(
    config_path: Path, *, data_dir: Path | None = None, manifest_path: Path | None = None,
    artifacts_dir: Path = Path("artifacts"),
) -> Path:  # fmt: skip
    """Load and check the data, run every variant, write the experiment folder."""
    started = utc_now()
    cfg, raw, text = load_leakage_config(config_path)
    data, manifest = load_checked_data(cfg.data, data_dir, manifest_path, artifacts_dir)
    result = run_experiment(data.X, data.y, data.time, cfg)
    run_hash = compute_run_hash(raw, cfg.seed, manifest.checksum, result["split_boundaries"])
    run_id = run_id_from_hash(run_hash).replace("run-", "leak-")
    out = artifacts_dir / "experiments" / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(text, encoding="utf-8")
    write_json(out / "results.json", {"run_id": run_id, "run_hash": run_hash, **result})
    (out / "summary.md").write_text(summary_markdown(result, run_id), encoding="utf-8")
    (out / "environment.txt").write_text(environment_text(), encoding="utf-8")
    (out / "git_sha.txt").write_text(git_sha(REPO_ROOT) + "\n", encoding="utf-8")
    (out / "manifest_checksum.txt").write_text(manifest.checksum + "\n", encoding="utf-8")
    write_execution(out, run_id, started, REPO_ROOT)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; known problems exit with code 2 and a one-line message."""
    parser = argparse.ArgumentParser(description="Stage E leakage experiment (validation only)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    args = parser.parse_args(argv)
    try:
        out = run(args.config, data_dir=args.data_dir, manifest_path=args.manifest,
                  artifacts_dir=args.artifacts_dir)  # fmt: skip
    except DatasetFileNotFoundError as err:
        print(f"ERROR: {err}\nCreate the manifest first: see shared/dataset-management/README.md",
              file=sys.stderr)  # fmt: skip
        return 2
    except KNOWN_ERRORS as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    print(f"experiment folder: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
