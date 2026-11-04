"""Repeated entities across partitions (ADR 0003): descriptive only, never used for decisions.

A time split does not stop the same card from appearing in train and in validation/test. If
many validation rows belong to cards already seen in train, a model can score well by
recognising cards instead of learning fraud behaviour.
"""

from typing import Any

import pandas as pd

from fraud_risk.evaluation.split import Split


def entity_key(X: pd.DataFrame, columns: list[str]) -> pd.Series:
    """One string per row from `columns`; rows with any missing part get no key (NaN)."""
    missing = [c for c in columns if c not in X.columns]
    if missing:
        raise KeyError(f"entity columns not in the data: {missing}")
    parts = X[columns]
    complete = parts.notna().all(axis=1)
    key = parts[columns[0]].astype(object).astype(str)
    for col in columns[1:]:
        key = key + "|" + parts[col].astype(object).astype(str)
    return key.astype(object).where(complete)


def entity_overlap(
    X: pd.DataFrame, y: pd.Series, split: Split, keys: list[list[str]]
) -> list[dict[str, Any]]:
    """For each key and each of valid/test: share of rows whose entity was seen in train.

    Fraud rates of seen vs new rows are given for validation only: test labels are not read
    outside the one-time test evaluation.
    """
    out = []
    for columns in keys:
        key = entity_key(X, columns)
        seen = set(key.loc[split.train].dropna())
        for part in ("valid", "test"):
            idx = getattr(split, part)
            k = key.loc[idx]
            has_key = k.notna()
            in_train = k.isin(seen) & has_key
            new = has_key & ~in_train
            yp = y.loc[idx] if part == "valid" else None
            out.append(
                {
                    "key": "+".join(columns),
                    "part": part,
                    "rows": int(len(idx)),
                    "rows_with_key": int(has_key.sum()),
                    "share_seen_in_train": float(in_train.sum() / max(has_key.sum(), 1)),
                    "fraud_rate_seen": _rate(yp, in_train),
                    "fraud_rate_new": _rate(yp, new),
                }
            )
    return out


def _rate(y: pd.Series | None, mask: pd.Series) -> float | None:
    return None if y is None or not mask.any() else float(y[mask].mean())
