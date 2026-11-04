"""Stage E model: scikit-learn HistGradientBoostingClassifier in one Pipeline fitted on TRAIN only.

No new dependency (ADR 0006). Trees need no scaling and handle missing values natively, so the
only preprocessing is an ordinal code for each categorical column (fitted on train; values not
seen in train become missing). Hyper-parameters come from a small grid chosen on validation.
"""

from itertools import product
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

MAX_CATEGORIES = 50  # same rule as the logistic baseline: no high-cardinality IDs


def param_grid(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Every combination of the grid, in a fixed order (sorted keys)."""
    keys = sorted(grid)
    return [dict(zip(keys, values, strict=True)) for values in product(*(grid[k] for k in keys))]


class GbmModel:
    """Ordinal-encoded categoricals + HistGradientBoosting with balanced class weights."""

    def __init__(
        self, numeric: list[str], categorical: list[str], *, seed: int, params: dict[str, Any]
    ) -> None:
        self.numeric = list(numeric)
        self.categorical = list(categorical)
        self.seed = seed
        self.params = dict(params)
        self.pipeline_: Pipeline | None = None
        self.fit_index_: pd.Index | None = None

    def build_pipeline(self) -> Pipeline:
        """Unfitted pipeline; the encoder is fitted together with the model, on train rows."""
        encoder = OrdinalEncoder(
            handle_unknown="use_encoded_value",
            unknown_value=np.nan,
            encoded_missing_value=np.nan,
        )
        prep = ColumnTransformer(
            [("num", "passthrough", self.numeric), ("cat", encoder, self.categorical)],
            verbose_feature_names_out=False,
        )
        n_num = len(self.numeric)
        model = HistGradientBoostingClassifier(
            categorical_features=list(range(n_num, n_num + len(self.categorical))),
            class_weight="balanced",
            early_stopping=False,  # its internal split would be random, not by time
            random_state=self.seed,
            **self.params,
        )
        return Pipeline([("prep", prep), ("model", model)])

    def fit(self, features_train: pd.DataFrame, y_train: pd.Series) -> "GbmModel":
        """Fit the whole pipeline on train rows only."""
        if not features_train.index.equals(y_train.index):
            raise ValueError("features_train and y_train must share the same index")
        too_many = {
            c: int(features_train[c].nunique())
            for c in self.categorical
            if features_train[c].nunique() > MAX_CATEGORIES
        }
        if too_many:
            raise ValueError(f"high-cardinality categoricals not allowed: {too_many}")
        cols = self.numeric + self.categorical
        pipeline = self.build_pipeline()
        pipeline.fit(features_train[cols], y_train)
        self.pipeline_ = pipeline
        self.fit_index_ = features_train.index.copy()
        return self

    def score(self, features: pd.DataFrame) -> np.ndarray:
        """Predicted fraud probability per row."""
        if self.pipeline_ is None:
            raise RuntimeError("call fit() before score()")
        return self.pipeline_.predict_proba(features[self.numeric + self.categorical])[:, 1]

    def describe(self) -> dict[str, Any]:
        """Parameters and size of the fitted model, for the run log."""
        if self.pipeline_ is None:
            raise RuntimeError("call fit() first")
        model = self.pipeline_.named_steps["model"]
        return {
            "params": {**self.params, "class_weight": "balanced", "early_stopping": False},
            "n_iter": int(model.n_iter_),
            "features": {"numeric": self.numeric, "categorical": self.categorical},
        }
