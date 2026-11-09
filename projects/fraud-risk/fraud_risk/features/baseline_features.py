"""Baseline feature builder. Takes features only: it has no access to the label (hard rule 6)."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

LABEL = "isFraud"
# Never usable as model inputs: the label, a row ID, and the raw time/order key.
FORBIDDEN_FEATURES = frozenset({LABEL, "TransactionID", "TransactionDT"})


# Entity keys for history features. card1 alone has ~13.6k values for 590k rows, so it mixes many
# customers; card1+addr1+P_emaildomain (~90k groups) is closer to one customer.
# "uidd" adds D1n = day of the transaction minus D1 (days since the card's first use, a common
# public heuristic): it stays constant for one card, so it separates customers sharing a uid.
HISTORY_KEYS = {
    "card1": ("card1",),
    "uid": ("card1", "addr1", "P_emaildomain"),
    "uidd": ("card1", "addr1", "P_emaildomain", "D1n"),
}
HISTORY_STATS = ("prev_count", "amt_vs_mean", "secs_since_prev")
# Windowed counts stay on one scale over time; the running `prev_count` grows with the date.
HISTORY_WINDOWS = {"count_24h": 24 * 3600, "count_7d": 7 * 24 * 3600}


def _entity_frame(X: pd.DataFrame, key: tuple[str, ...]) -> pd.DataFrame:
    """X plus the derived key column `D1n` when the key needs it (no label involved)."""
    if "D1n" in key:
        X = X.assign(D1n=X["TransactionDT"] // 86400 - X["D1"])
    return X


def _source_columns(key: tuple[str, ...]) -> tuple[str, ...]:
    """Raw input columns a key is built from."""
    return tuple(c for k in key for c in (("D1", "TransactionDT") if k == "D1n" else (k,)))


def _history(X: pd.DataFrame, key: tuple[str, ...], stat: str) -> pd.Series:
    """Behaviour of the same entity from EARLIER transactions only, no labels: what a live system
    knows. Rows are taken in time order; ties keep file order, so a same-second transaction sees
    the one listed before it but never the one after.
    """
    X = _entity_frame(X, key)
    s = X.sort_values("TransactionDT", kind="stable")
    g = s.groupby(list(key), dropna=False, sort=False)
    if stat == "prev_count":
        out = g.cumcount()
    elif stat == "amt_vs_mean":
        prev_sum = g["TransactionAmt"].cumsum() - s["TransactionAmt"]
        # First transaction: 0/0 = NaN. A zero past mean would give inf, which models reject.
        ratio = s["TransactionAmt"] / (prev_sum / g.cumcount())
        out = ratio.replace([np.inf, -np.inf], np.nan)
    else:  # secs_since_prev
        out = s["TransactionDT"] - g["TransactionDT"].shift()
    return out.reindex(X.index)


def _window_count(X: pd.DataFrame, key: tuple[str, ...], seconds: int) -> pd.Series:
    """Earlier transactions of the same entity within `seconds` before this one (no labels).

    Rows are ordered by entity then time (ties keep file order), so a same-second transaction
    counts the one listed before it but never the one after, as in `_history`.
    """
    X = _entity_frame(X, key)
    gid = X.groupby(list(key), dropna=False, sort=False).ngroup().to_numpy(dtype="int64")
    t = X["TransactionDT"].to_numpy(dtype="int64")
    order = np.lexsort((t, gid))  # stable: gid first, then time
    scale = 1 << 40  # larger than any TransactionDT, so gid * scale + t sorts by (gid, t)
    combined = gid[order] * scale + t[order]
    lower = np.searchsorted(combined, combined - seconds, side="left")
    counts = np.empty(len(X), dtype="int64")
    counts[order] = np.arange(len(X)) - lower
    return pd.Series(counts, index=X.index)


DERIVED_FEATURES = {
    "log_amount": (("TransactionAmt",), lambda X: np.log1p(X["TransactionAmt"].clip(lower=0))),
    "hour_of_day": (("TransactionDT",), lambda X: (X["TransactionDT"] // 3600) % 24),
    **{
        f"{k}_{stat}": (
            (*_source_columns(key), "TransactionAmt", "TransactionDT"),
            lambda X, key=key, stat=stat: _history(X, key, stat),
        )
        for k, key in HISTORY_KEYS.items()
        for stat in HISTORY_STATS
    },
    **{
        f"{k}_{name}": (
            (*_source_columns(key), "TransactionDT"),
            lambda X, key=key, seconds=seconds: _window_count(X, key, seconds),
        )
        for k, key in HISTORY_KEYS.items()
        for name, seconds in HISTORY_WINDOWS.items()
    },
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
    sources = {c for d in spec.derived for c in DERIVED_FEATURES[d][0]}
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
