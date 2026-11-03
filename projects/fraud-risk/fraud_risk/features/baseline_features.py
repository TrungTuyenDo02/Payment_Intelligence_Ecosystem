"""Baseline feature builder. Takes features only: it has no access to the label (hard rule 6)."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

LABEL = "isFraud"
# Never usable as model inputs: the label, a row ID, and the raw time/order key.
FORBIDDEN_FEATURES = frozenset({LABEL, "TransactionID", "TransactionDT"})
DERIVED_FEATURES = {
    "log_amount": ("TransactionAmt", lambda X: np.log1p(X["TransactionAmt"].clip(lower=0))),
    "hour_of_day": ("TransactionDT", lambda X: (X["TransactionDT"] // 3600) % 24),
}


class FeatureSpecError(ValueError):
    """The feature list is invalid (unknown, forbidden or duplicated columns)."""


class LabelLeakError(ValueError):
    """The label, or a column derived from it, reached the feature matrix."""


@dataclass(frozen=True)
class FeatureSpec:
    """Explicit feature list from the YAML config."""

    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    derived: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "FeatureSpec":
        """Build and validate a spec from the `features` config section."""
        spec = cls(
            numeric=tuple(cfg.get("numeric", [])),
            categorical=tuple(cfg.get("categorical", [])),
            derived=tuple(cfg.get("derived", [])),
        )
        names = spec.numeric + spec.categorical + spec.derived
        if not names:
            raise FeatureSpecError("feature list is empty")
        if len(set(names)) != len(names):
            raise FeatureSpecError("a feature is listed twice")
        if forbidden := (set(names) & FORBIDDEN_FEATURES) or {n for n in names if LABEL in n}:
            raise FeatureSpecError(f"forbidden feature(s): {sorted(forbidden)}")
        if unknown := set(spec.derived) - DERIVED_FEATURES.keys():
            raise FeatureSpecError(f"unknown derived feature(s): {sorted(unknown)}")
        return spec

    @property
    def numeric_out(self) -> list[str]:
        """Numeric columns of the built matrix (raw numeric + derived)."""
        return [*self.numeric, *self.derived]

    @property
    def categorical_out(self) -> list[str]:
        """Categorical columns of the built matrix."""
        return list(self.categorical)


def build_features(X: pd.DataFrame, spec: FeatureSpec) -> pd.DataFrame:
    """Select and derive the configured features. Stateless: nothing is fitted here."""
    if LABEL in X.columns:
        raise LabelLeakError(f"'{LABEL}' must not be in the input of build_features")
    sources = {DERIVED_FEATURES[d][0] for d in spec.derived}
    if missing := [c for c in [*spec.numeric, *spec.categorical, *sources] if c not in X.columns]:
        raise FeatureSpecError(f"missing input column(s): {missing}")
    out = pd.DataFrame(index=X.index)
    for col in spec.numeric:
        out[col] = X[col].astype("float64")
    for name in spec.derived:
        out[name] = DERIVED_FEATURES[name][1](X).astype("float64")
    for col in spec.categorical:
        out[col] = X[col].astype(object).where(X[col].notna(), np.nan)
    return out
