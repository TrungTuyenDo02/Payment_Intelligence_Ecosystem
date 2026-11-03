"""Data profiling (EDA) on the TRAIN partition: tables and figures, no conclusions.

Six steps (AGENTS.md section 8): profile, missing values, class imbalance, distributions
and outliers, categoricals, leakage candidates. Every table that could drive a
preprocessing decision is computed on train rows only. The single all-data table is
named `*_descriptive_only_all_data.csv` and must not feed a decision (hard rule 12).

Run: python -m fraud_risk.eda.profile [--config CONFIG] [--with-identity]
"""

import argparse
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score

from fraud_risk.adapters.ieee_cis import DatasetNotFoundError, IeeeCisSchemaError, load_ieee_cis
from fraud_risk.evaluation.split import Split, SplitError, time_split

TIME = "TransactionDT"
AMOUNT = "TransactionAmt"
WEEK_SECONDS = 7 * 86_400
RARE_SHARE = 0.01
TOP_VALUES = 100
AUC_FLAG = 0.95
TIME_CORR_FLAG = 0.95
IDENTITY_MARKER = "DeviceType"


def _week(time: pd.Series) -> pd.Series:
    return (time // WEEK_SECONDS).astype("int64").rename("week")


def _categorical_columns(X: pd.DataFrame) -> list[str]:
    return [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]


def _numeric_columns(X: pd.DataFrame) -> list[str]:
    return [c for c in X.columns if pd.api.types.is_numeric_dtype(X[c])]


def step1_profile(X: pd.DataFrame, y: pd.Series) -> dict[str, pd.DataFrame]:
    """Row/column counts, dtypes, memory and fraud rate (train)."""
    summary = pd.DataFrame(
        {
            "metric": [
                "rows",
                "columns",
                "memory_mb",
                "numeric_columns",
                "categorical_columns",
                "fraud_rows",
                "fraud_rate",
            ],
            "value": [
                len(X),
                X.shape[1],
                round(X.memory_usage(deep=True).sum() / 1e6, 2),
                len(_numeric_columns(X)),
                len(_categorical_columns(X)),
                int(y.sum()),
                float(y.mean()),
            ],
        }
    )
    dtypes = pd.DataFrame({"column": X.columns, "dtype": X.dtypes.astype(str).to_numpy()})
    return {"01_profile": summary, "01_dtypes": dtypes}


def descriptive_fraud_rate_all_data(time: pd.Series, y: pd.Series, split: Split) -> pd.DataFrame:
    """DESCRIPTIVE ONLY: weekly fraud rate over all partitions. Never feeds a decision."""
    part = pd.Series("test", index=time.index)
    part[split.train] = "train"
    part[split.valid] = "valid"
    frame = pd.DataFrame({"week": _week(time), "partition": part, "isFraud": y})
    out = frame.groupby(["week", "partition"])["isFraud"].agg(rows="size", fraud_rate="mean")
    return out.reset_index()


def step2_missing(X: pd.DataFrame, y: pd.Series) -> dict[str, pd.DataFrame]:
    """Missing rate per column, by class, and groups of columns missing together."""
    miss = X.isna()
    by_col = pd.DataFrame(
        {
            "column": X.columns,
            "missing_rate": miss.mean().to_numpy(),
            "missing_rate_fraud": miss[y == 1].mean().to_numpy(),
            "missing_rate_nonfraud": miss[y == 0].mean().to_numpy(),
        }
    )
    by_col["diff_fraud_minus_nonfraud"] = (
        by_col["missing_rate_fraud"] - by_col["missing_rate_nonfraud"]
    )
    by_col = by_col.sort_values(["missing_rate", "column"], ascending=[False, True])

    partial = [c for c in X.columns if 0 < miss[c].mean() < 1]
    signatures: dict[bytes, list[str]] = {}
    for col in partial:
        signatures.setdefault(np.packbits(miss[col].to_numpy()).tobytes(), []).append(col)
    groups = [
        {
            "n_columns": len(cols),
            "missing_rate": float(miss[cols[0]].mean()),
            "columns": ";".join(cols),
        }
        for cols in signatures.values()
        if len(cols) > 1
    ]
    groups_df = pd.DataFrame(groups, columns=["n_columns", "missing_rate", "columns"])
    groups_df = groups_df.sort_values(["n_columns", "columns"], ascending=[False, True])
    groups_df.insert(0, "group_id", range(1, len(groups_df) + 1))
    return {"02_missing_by_column": by_col, "02_missing_groups": groups_df}


def step2_identity_effect(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    """Share of train rows with an identity record and fraud rate with/without it."""
    if IDENTITY_MARKER not in X.columns:
        return pd.DataFrame({"note": ["identity join off; rerun with --with-identity"]})
    identity_cols = [c for c in X.columns if c.startswith("id_") or c.startswith("Device")]
    has_identity = X[identity_cols].notna().any(axis=1)
    return pd.DataFrame(
        {
            "group": ["with_identity", "without_identity"],
            "rows": [int(has_identity.sum()), int((~has_identity).sum())],
            "share": [float(has_identity.mean()), float((~has_identity).mean())],
            "fraud_rate": [float(y[has_identity].mean()), float(y[~has_identity].mean())],
        }
    )


def step3_class_balance(time: pd.Series, y: pd.Series) -> dict[str, pd.DataFrame]:
    """Weekly fraud rate on train and inputs for class_weight."""
    weekly = (
        pd.DataFrame({"week": _week(time), "isFraud": y})
        .groupby("week")["isFraud"]
        .agg(rows="size", fraud_rows="sum", fraud_rate="mean")
        .reset_index()
    )
    n, pos = len(y), int(y.sum())
    neg = n - pos
    summary = pd.DataFrame(
        {
            "metric": [
                "fraud_rate",
                "negative_to_positive_ratio",
                "balanced_weight_positive",
                "balanced_weight_negative",
                "weeks",
                "weekly_fraud_rate_min",
                "weekly_fraud_rate_max",
                "weekly_fraud_rate_std",
            ],
            "value": [
                pos / n,
                neg / pos if pos else np.nan,
                n / (2 * pos) if pos else np.nan,
                n / (2 * neg) if neg else np.nan,
                len(weekly),
                weekly["fraud_rate"].min(),
                weekly["fraud_rate"].max(),
                weekly["fraud_rate"].std(),
            ],
        }
    )
    return {"03_class_balance_by_week": weekly, "03_class_balance_summary": summary}


def step4_distributions(X: pd.DataFrame) -> pd.DataFrame:
    """Quantiles, skewness and extremes for amount and C1-C14, raw vs log1p."""
    cols = [c for c in [AMOUNT] + [f"C{i}" for i in range(1, 15)] if c in X.columns]
    rows = []
    for col in cols:
        s = X[col].dropna().astype("float64")
        q = s.quantile([0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 0.999, 1.0])
        logged = np.log1p(s.clip(lower=0))
        rows.append(
            {
                "column": col,
                "count": len(s),
                "missing_rate": float(X[col].isna().mean()),
                "mean": s.mean(),
                "std": s.std(),
                **{f"q{k:g}": v for k, v in q.items()},
                "n_above_q99": int((s > q[0.99]).sum()),
                "n_negative": int((s < 0).sum()),
                "skew_raw": s.skew(),
                "skew_log1p": logged.skew(),
                "std_log1p": logged.std(),
            }
        )
    return pd.DataFrame(rows)


def step5_categoricals(X: pd.DataFrame, y: pd.Series) -> dict[str, pd.DataFrame]:
    """Distinct values, rare share and fraud rate per value (train)."""
    summary, values = [], []
    for col in _categorical_columns(X):
        s = X[col].astype(object).where(X[col].notna(), "(missing)")
        stats = (
            pd.DataFrame({"value": s, "isFraud": y})
            .groupby("value")["isFraud"]
            .agg(count="size", fraud_rate="mean")
            .reset_index()
            .sort_values(["count", "value"], ascending=[False, True])
        )
        stats["share"] = stats["count"] / len(s)
        stats["is_rare"] = stats["share"] < RARE_SHARE
        summary.append(
            {
                "column": col,
                "n_unique": int(X[col].nunique()),
                "missing_rate": float(X[col].isna().mean()),
                "n_rare_values": int(stats["is_rare"].sum()),
                "rare_rows_share": float(stats.loc[stats["is_rare"], "share"].sum()),
            }
        )
        top = stats.head(TOP_VALUES).assign(column=col)
        values.append(top[["column", "value", "count", "share", "fraud_rate", "is_rare"]])
    values_df = (
        pd.concat(values, ignore_index=True)
        if values
        else pd.DataFrame(columns=["column", "value", "count", "share", "fraud_rate", "is_rare"])
    )
    return {"05_categorical_summary": pd.DataFrame(summary), "05_categorical_values": values_df}


def _single_column_auc(s: pd.Series, y: pd.Series) -> float:
    """In-sample AUC of one column (categoricals target-encoded on the same rows: optimistic)."""
    if not pd.api.types.is_numeric_dtype(s):
        key = s.astype(object).where(s.notna(), "(missing)")
        s = key.map(y.groupby(key).mean())
    s = s.astype("float64")
    s = s.fillna(s.min() - 1 if s.notna().any() else 0.0)
    if s.nunique() < 2 or y.nunique() < 2:
        return 0.5
    return float(roc_auc_score(y, s))


def step6_leakage(X: pd.DataFrame, y: pd.Series, time: pd.Series) -> dict[str, pd.DataFrame]:
    """Flag columns unique per row, near-perfect with the label, or encoding time/order."""
    time_rank = time.rank()
    rows = []
    for col in X.columns:
        s = X[col]
        unique_per_row = bool(s.notna().all() and s.nunique() == len(s))
        auc = _single_column_auc(s, y)
        corr = np.nan
        if pd.api.types.is_numeric_dtype(s) and s.notna().sum() >= 30:
            corr = float(s.rank().corr(time_rank))
        reasons = []
        if unique_per_row:
            reasons.append("unique_per_row")
        if max(auc, 1 - auc) >= AUC_FLAG:
            reasons.append("near_perfect_label_association")
        if not np.isnan(corr) and abs(corr) >= TIME_CORR_FLAG:
            reasons.append("encodes_time_or_order")
        rows.append(
            {
                "column": col,
                "unique_per_row": unique_per_row,
                "single_column_auc_in_sample": auc,
                "spearman_with_time": corr,
                "reasons": ";".join(reasons),
            }
        )
    checks = pd.DataFrame(rows)
    # The index (TransactionID) is not a column of X; check it too.
    index_corr = float(pd.Series(X.index, index=X.index).rank().corr(time_rank))
    index_row = {
        "column": f"(index) {X.index.name}",
        "unique_per_row": X.index.is_unique,
        "single_column_auc_in_sample": _single_column_auc(
            pd.Series(X.index, index=X.index).astype("float64"), y
        ),
        "spearman_with_time": index_corr,
        "reasons": ";".join(
            ["unique_per_row"] * X.index.is_unique
            + ["encodes_time_or_order"] * (abs(index_corr) >= TIME_CORR_FLAG)
        ),
    }
    checks = pd.concat([checks, pd.DataFrame([index_row])], ignore_index=True)
    return {"06_column_checks": checks, "06_leakage_candidates": checks[checks["reasons"] != ""]}


def _figures(X: pd.DataFrame, weekly: pd.DataFrame, out_dir: Path) -> None:
    matplotlib.use("Agg")  # headless backend; must be set before pyplot is imported
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(weekly["week"], weekly["fraud_rate"], marker="o")
    ax.set(title="Fraud rate per week (train)", xlabel="week index", ylabel="fraud rate")
    fig.tight_layout()
    fig.savefig(out_dir / "03_fraud_rate_by_week_train.png", dpi=100)
    plt.close(fig)
    if AMOUNT in X.columns:
        amount = X[AMOUNT].dropna()
        fig, axes = plt.subplots(1, 2, figsize=(10, 3))
        axes[0].hist(amount, bins=50)
        axes[0].set(title="TransactionAmt (train)", xlabel="amount")
        axes[1].hist(np.log1p(amount.clip(lower=0)), bins=50)
        axes[1].set(title="log1p(TransactionAmt) (train)", xlabel="log1p(amount)")
        fig.tight_layout()
        fig.savefig(out_dir / "04_transaction_amt_raw_vs_log.png", dpi=100)
        plt.close(fig)


def run_profile(
    X: pd.DataFrame, y: pd.Series, time: pd.Series, split: Split, out_dir: Path
) -> list[Path]:
    """Compute all six steps on train rows and write tables/figures to `out_dir`."""
    if split.kind != "time":
        raise SplitError("EDA requires the chronological split")
    X_tr, y_tr, t_tr = X.loc[split.train], y.loc[split.train], time.loc[split.train]
    tables: dict[str, pd.DataFrame] = {}
    tables.update(step1_profile(X_tr, y_tr))
    tables.update(step2_missing(X_tr, y_tr))
    tables["02_identity_effect"] = step2_identity_effect(X_tr, y_tr)
    tables.update(step3_class_balance(t_tr, y_tr))
    tables["04_distributions"] = step4_distributions(X_tr)
    tables.update(step5_categoricals(X_tr, y_tr))
    tables.update(step6_leakage(X_tr, y_tr, t_tr))
    tables["01_fraud_rate_by_week_descriptive_only_all_data"] = descriptive_fraud_rate_all_data(
        time, y, split
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, table in sorted(tables.items()):
        path = out_dir / f"{name}.csv"
        table.to_csv(path, index=False, float_format="%.6g")
        written.append(path)
    _figures(X_tr, tables["03_class_balance_by_week"], out_dir)
    return written


def _split_fractions(config: Path | None) -> tuple[float, float]:
    if config is None:
        return 0.6, 0.2
    split = yaml.safe_load(config.read_text("utf-8"))["split"]
    return float(split["train_frac"]), float(split["valid_frac"])


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    parser = argparse.ArgumentParser(description="EDA on the IEEE-CIS train partition")
    parser.add_argument("--config", type=Path, default=None, help="YAML with a split section")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/eda"))
    parser.add_argument("--with-identity", action="store_true")
    args = parser.parse_args(argv)
    try:
        data = load_ieee_cis(args.data_dir, use_identity=args.with_identity)
        train_frac, valid_frac = _split_fractions(args.config)
        split = time_split(data.time, train_frac, valid_frac)
        written = run_profile(data.X, data.y, data.time, split, args.out_dir)
    except (DatasetNotFoundError, IeeeCisSchemaError, SplitError) as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 2
    print(f"split fractions train={train_frac} valid={valid_frac}; rows {split.to_dict()['rows']}")
    print(f"wrote {len(written)} tables and figures to {args.out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
