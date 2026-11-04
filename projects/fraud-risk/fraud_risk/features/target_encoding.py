"""Smoothed target (mean) encoding of one categorical column, fitted on the rows it is given.

    enc(v) = (sum of labels for v + m * prior) / (count of v + m)

`m` (smoothing) pulls rare values towards the prior. Values never seen in the fitted rows get the
prior. Fitting on train rows only is legitimate; fitting on rows that include the evaluation
partition copies its labels into a feature (the leaky variant of the Stage E experiment).

Train rows themselves are encoded out-of-fold (`encode_out_of_fold`): each block of train is
encoded with the labels of the other blocks. Encoding a row with its own label would let the
model learn to trust the feature too much (a small leak inside train).
"""

import numpy as np
import pandas as pd


class TargetEncoder:
    """Fit on (column values, labels) of chosen rows; transform any rows."""

    def __init__(self, smoothing: float = 100.0) -> None:
        if smoothing < 0:
            raise ValueError("smoothing must be >= 0")
        self.smoothing = smoothing
        self.prior_: float | None = None
        self.table_: pd.Series | None = None
        self.fit_index_: pd.Index | None = None

    def fit(self, values: pd.Series, y: pd.Series) -> "TargetEncoder":
        if not values.index.equals(y.index):
            raise ValueError("values and y must share the same index")
        self.prior_ = float(y.mean())
        stats = y.groupby(values.astype(object), dropna=True).agg(["sum", "count"])
        m = self.smoothing
        self.table_ = (stats["sum"] + m * self.prior_) / (stats["count"] + m)
        self.fit_index_ = values.index.copy()
        return self

    def transform(self, values: pd.Series) -> pd.Series:
        if self.table_ is None or self.prior_ is None:
            raise RuntimeError("call fit() before transform()")
        mapped = values.astype(object).map(self.table_)
        return mapped.fillna(self.prior_).astype("float64")


def encode_out_of_fold(
    values: pd.Series, y: pd.Series, order: pd.Series, n_folds: int = 5, smoothing: float = 100.0
) -> pd.Series:
    """Encode `values` (train rows) in `n_folds` contiguous blocks of `order` (time).

    Each block uses an encoder fitted on the other blocks only.
    """
    if n_folds < 2:
        raise ValueError("n_folds must be >= 2")
    ranked = order.loc[values.index].sort_values(kind="stable").index
    out = pd.Series(np.nan, index=values.index, dtype="float64")
    for block in np.array_split(np.arange(len(ranked)), n_folds):
        held_out = ranked[block]
        rest = ranked.difference(held_out)
        encoder = TargetEncoder(smoothing).fit(values.loc[rest], y.loc[rest])
        out.loc[held_out] = encoder.transform(values.loc[held_out]).to_numpy()
    return out
