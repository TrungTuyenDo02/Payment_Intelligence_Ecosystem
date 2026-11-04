"""Chronological train / validation / test split.

Boundaries are time values, so rows that share a timestamp always land in the same part.
`random_split` exists only for the later leakage experiment and must never be used by
baselines (the baseline runner rejects any split whose `kind` is not "time").

`gap_days` (ADR 0003, Stage E) drops the last N days of train: a model trained at the start of
validation would not yet know those labels (chargebacks arrive late). Validation and test do not
change, so results with and without a gap are compared on the same rows.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

DAY_SECONDS = 86_400


class SplitError(ValueError):
    """The split cannot be built or violates the chronological rule."""


@dataclass(frozen=True)
class Split:
    """Row index labels per part plus the time boundaries used."""

    kind: str  # "time" or "random"
    train: pd.Index
    valid: pd.Index
    test: pd.Index
    boundaries: dict[str, Any]
    excluded: pd.Index = field(default_factory=lambda: pd.Index([]))  # rows in the gap

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly summary for the run log."""
        rows = {"train": len(self.train), "valid": len(self.valid), "test": len(self.test)}
        if len(self.excluded):
            rows["gap_excluded"] = len(self.excluded)
        return {"kind": self.kind, "rows": rows, "boundaries": self.boundaries}


def _check_fractions(train_frac: float, valid_frac: float) -> None:
    if not (0 < train_frac < 1 and 0 < valid_frac < 1 and train_frac + valid_frac < 1):
        raise SplitError("need 0 < train_frac, valid_frac and train_frac + valid_frac < 1")


def time_split(
    time: pd.Series, train_frac: float = 0.6, valid_frac: float = 0.2, gap_days: float = 0
) -> Split:
    """Split rows by time into train, validation and test (in that order).

    The cut is placed at a timestamp: all rows at or before the cut time go to the earlier part,
    so fractions are approximate when timestamps repeat. With `gap_days > 0`, train rows later
    than `train max time - gap_days` are excluded; validation and test stay the same.
    """
    _check_fractions(train_frac, valid_frac)
    if gap_days < 0:
        raise SplitError("gap_days must be >= 0")
    if time.isna().any():
        raise SplitError("time column contains missing values")
    if not time.index.is_unique:
        raise SplitError("index must be unique")
    ordered = np.sort(time.to_numpy(), kind="stable")
    n = len(ordered)
    cut_train = ordered[max(int(round(n * train_frac)) - 1, 0)]
    cut_valid = ordered[max(int(round(n * (train_frac + valid_frac))) - 1, 0)]

    valid_mask = (time > cut_train) & (time <= cut_valid)
    test_mask = time > cut_valid
    gap_mask = (time <= cut_train) & (time > cut_train - gap_days * DAY_SECONDS)
    if not gap_days:
        gap_mask = pd.Series(False, index=time.index)
    train_mask = (time <= cut_train) & ~gap_mask
    parts = {"train": train_mask, "valid": valid_mask, "test": test_mask}
    empty = [name for name, mask in parts.items() if not mask.any()]
    if empty:
        raise SplitError(f"empty part(s) {empty}: too few distinct timestamps for these fractions")

    def _bounds(mask: pd.Series) -> dict[str, int | float]:
        return {"min_time": time[mask].min().item(), "max_time": time[mask].max().item()}

    boundaries: dict[str, Any] = {
        "train_frac": train_frac,
        "valid_frac": valid_frac,
        "train": _bounds(train_mask),
        "valid": _bounds(valid_mask),
        "test": _bounds(test_mask),
    }
    if gap_days:  # only then, so run ids of gap-free configs stay what they were (D6)
        boundaries["gap_days"] = gap_days
        boundaries["gap"] = {"rows": int(gap_mask.sum()), "train_cut_time": cut_train.item()}
    split = Split(
        kind="time",
        train=time.index[train_mask.to_numpy()],
        valid=time.index[valid_mask.to_numpy()],
        test=time.index[test_mask.to_numpy()],
        boundaries=boundaries,
        excluded=time.index[gap_mask.to_numpy()],
    )
    assert_no_time_overlap(split, time)
    return split


def assert_no_time_overlap(split: Split, time: pd.Series) -> None:
    """Raise if any train row is later than a valid row, or any valid row later than a test row."""
    if split.kind != "time":
        raise SplitError(f"expected a time split, got kind={split.kind!r}")
    if time[split.train].max() >= time[split.valid].min():
        raise SplitError("train overlaps validation in time")
    if time[split.valid].max() >= time[split.test].min():
        raise SplitError("validation overlaps test in time")
    covered = len(split.train) + len(split.valid) + len(split.test) + len(split.excluded)
    if covered != len(time):
        raise SplitError("parts (and the gap) do not cover every row exactly once")


def random_split(
    index: pd.Index, train_frac: float = 0.6, valid_frac: float = 0.2, seed: int = 0
) -> Split:
    """LEAKY random split. Only for the leakage experiment (Stage E); never for baselines."""
    _check_fractions(train_frac, valid_frac)
    order = np.random.default_rng(seed).permutation(len(index))
    n_train = int(round(len(index) * train_frac))
    n_valid = int(round(len(index) * (train_frac + valid_frac)))
    return Split(
        kind="random",
        train=index[order[:n_train]],
        valid=index[order[n_train:n_valid]],
        test=index[order[n_valid:]],
        boundaries={"train_frac": train_frac, "valid_frac": valid_frac, "seed": seed},
    )
