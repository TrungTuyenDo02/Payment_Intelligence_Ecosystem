"""Baseline 2: Logistic Regression in a single scikit-learn Pipeline fitted on TRAIN only."""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

MAX_CATEGORIES = 50  # one-hot only for low-cardinality columns


class LogisticBaseline:
    """Median imputation + scaling (numeric), one-hot (categorical), balanced LR."""

    def __init__(
        self,
        numeric: list[str],
        categorical: list[str],
        *,
        seed: int,
        C: float = 1.0,
        max_iter: int = 1000,
    ) -> None:
        self.numeric = list(numeric)
        self.categorical = list(categorical)
        self.seed = seed
        self.C = C
        self.max_iter = max_iter
        self.pipeline_: Pipeline | None = None
        self.fit_index_: pd.Index | None = None

    def build_pipeline(self) -> Pipeline:
        """Unfitted pipeline; every transformer inside is fitted together with the model."""
        numeric = Pipeline(
            [("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]
        )
        categorical = Pipeline(
            [
                ("impute", SimpleImputer(strategy="constant", fill_value="missing")),
                ("onehot", OneHotEncoder(handle_unknown="ignore")),
            ]
        )
        prep = ColumnTransformer(
            [("num", numeric, self.numeric), ("cat", categorical, self.categorical)]
        )
        model = LogisticRegression(
            class_weight="balanced", max_iter=self.max_iter, C=self.C, random_state=self.seed
        )
        return Pipeline([("prep", prep), ("model", model)])

    def fit(self, features_train: pd.DataFrame, y_train: pd.Series) -> "LogisticBaseline":
        """Fit the whole pipeline on train rows only."""
        if not features_train.index.equals(y_train.index):
            raise ValueError("features_train and y_train must share the same index")
        too_many = {
            c: int(features_train[c].nunique())
            for c in self.categorical
            if features_train[c].nunique() > MAX_CATEGORIES
        }
        if too_many:
            raise ValueError(f"high-cardinality categoricals not allowed for one-hot: {too_many}")
        pipeline = self.build_pipeline()
        pipeline.fit(features_train[self.numeric + self.categorical], y_train)
        self.pipeline_ = pipeline
        self.fit_index_ = features_train.index.copy()
        return self

    def score(self, features: pd.DataFrame) -> np.ndarray:
        """Predicted fraud probability per row."""
        if self.pipeline_ is None:
            raise RuntimeError("call fit() before score()")
        return self.pipeline_.predict_proba(features[self.numeric + self.categorical])[:, 1]

    def describe(self) -> dict[str, Any]:
        """Coefficients by feature name, for the run log."""
        if self.pipeline_ is None:
            raise RuntimeError("call fit() first")
        names = self.pipeline_.named_steps["prep"].get_feature_names_out()
        model = self.pipeline_.named_steps["model"]
        coefs = dict(zip(names, model.coef_[0].round(6).tolist(), strict=True))
        return {
            "intercept": round(float(model.intercept_[0]), 6),
            "n_iter": int(model.n_iter_[0]),
            "coefficients": coefs,
            "params": {"C": self.C, "max_iter": self.max_iter, "class_weight": "balanced"},
        }
