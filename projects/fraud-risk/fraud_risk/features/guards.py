"""Leakage guards run on the built feature matrix before any model is fitted."""

import pandas as pd

from fraud_risk.features.baseline_features import LABEL, LabelLeakError


def check_label_leakage(features: pd.DataFrame, y: pd.Series) -> None:
    """Raise if a feature is named like the label or reproduces it (or its inverse) exactly."""
    if not features.index.equals(y.index):
        raise ValueError("features and y must share the same index")
    for col in features.columns:
        if LABEL.lower() in col.lower():
            raise LabelLeakError(f"feature '{col}' is named after the label")
        values = features[col]
        if values.isna().any() or values.nunique() != 2 or y.nunique() != 2:
            continue
        codes = pd.Series(pd.factorize(values, sort=True)[0], index=values.index)
        if codes.equals(y.astype("int64")) or codes.equals(1 - y.astype("int64")):
            raise LabelLeakError(f"feature '{col}' reproduces the label exactly")
