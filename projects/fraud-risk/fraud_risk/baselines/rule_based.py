"""Baseline 1: transparent rules with thresholds learned from the TRAIN partition only.

Score = fraction of rules triggered, so it lies in [0, 1] and can be evaluated with the
same metrics as a model. Missing values never trigger a rule.

Rule types (configured in YAML):
- `numeric_above_quantile`: value > train quantile `q` of `column`.
- `category_fraud_rate`: value is in the set of categories whose train fraud rate is at
  least `rate_multiplier` x the overall train fraud rate (and with >= `min_count` train rows).
"""

from typing import Any

import numpy as np
import pandas as pd

RULE_TYPES = {"numeric_above_quantile", "category_fraud_rate"}


class RuleConfigError(ValueError):
    """A rule definition is incomplete or unknown."""


class RuleBasedBaseline:
    """Fit on train once, then score any partition with the frozen thresholds."""

    def __init__(self, rules: list[dict[str, Any]]) -> None:
        if not rules:
            raise RuleConfigError("at least one rule is required")
        for rule in rules:
            if rule.get("type") not in RULE_TYPES:
                raise RuleConfigError(f"unknown rule type in {rule}")
            needed = {"name", "column"} | (
                {"quantile"}
                if rule["type"] == "numeric_above_quantile"
                else {"rate_multiplier", "min_count"}
            )
            if missing := needed - rule.keys():
                raise RuleConfigError(f"rule {rule.get('name')}: missing {sorted(missing)}")
        self.rules = rules
        self.fitted_: list[dict[str, Any]] | None = None
        self.fit_index_: pd.Index | None = None

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series) -> "RuleBasedBaseline":
        """Learn every threshold / category set from train rows."""
        if not X_train.index.equals(y_train.index):
            raise ValueError("X_train and y_train must share the same index")
        overall = float(y_train.mean())
        fitted = []
        for rule in self.rules:
            col = X_train[rule["column"]]
            learned: dict[str, Any] = {**rule}
            if rule["type"] == "numeric_above_quantile":
                learned["threshold"] = float(col.quantile(rule["quantile"]))
            else:
                stats = (
                    pd.DataFrame({"value": col, "y": y_train})
                    .dropna(subset=["value"])
                    .groupby("value")["y"]
                    .agg(["size", "mean"])
                )
                cutoff = rule["rate_multiplier"] * overall
                risky = stats[(stats["size"] >= rule["min_count"]) & (stats["mean"] >= cutoff)]
                learned["overall_train_fraud_rate"] = overall
                learned["rate_cutoff"] = cutoff
                learned["risky_values"] = sorted(str(v) for v in risky.index)
            fitted.append(learned)
        self.fitted_ = fitted
        self.fit_index_ = X_train.index.copy()
        return self

    def _triggers(self, X: pd.DataFrame) -> pd.DataFrame:
        if self.fitted_ is None:
            raise RuntimeError("call fit() before score()")
        out = {}
        for rule in self.fitted_:
            col = X[rule["column"]]
            if rule["type"] == "numeric_above_quantile":
                hit = col > rule["threshold"]
            else:
                hit = col.astype(object).where(col.notna()).isin(rule["risky_values"])
            out[rule["name"]] = hit.fillna(False).astype(bool)
        return pd.DataFrame(out, index=X.index)

    def score(self, X: pd.DataFrame) -> np.ndarray:
        """Fraction of rules triggered per row, in [0, 1]."""
        return self._triggers(X).mean(axis=1).to_numpy(dtype=float)

    def describe(self) -> list[dict[str, Any]]:
        """Rules with their learned thresholds, for the run log."""
        if self.fitted_ is None:
            raise RuntimeError("call fit() first")
        return [dict(rule) for rule in self.fitted_]
