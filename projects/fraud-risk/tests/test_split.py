"""Tests for the chronological split (T05)."""

import pandas as pd
import pytest
from fraud_risk.evaluation.split import (
    SplitError,
    assert_no_time_overlap,
    random_split,
    time_split,
)


@pytest.fixture
def time() -> pd.Series:
    # Unsorted on purpose; values 0..99 shuffled, index labels are not positions.
    values = pd.Series(range(100)).sample(frac=1, random_state=1).to_numpy()
    return pd.Series(values, index=pd.Index(range(1000, 1100), name="TransactionID"))


def test_chronological_no_overlap(time: pd.Series) -> None:
    s = time_split(time)
    assert time[s.train].max() < time[s.valid].min()
    assert time[s.valid].max() < time[s.test].min()
    # every train row earlier than every valid row; every valid row earlier than every test row
    assert (time[s.train].to_numpy()[:, None] < time[s.valid].to_numpy()[None, :]).all()
    assert (time[s.valid].to_numpy()[:, None] < time[s.test].to_numpy()[None, :]).all()
    assert (len(s.train), len(s.valid), len(s.test)) == (60, 20, 20)
    assert set(s.train) | set(s.valid) | set(s.test) == set(time.index)


def test_ties_never_straddle_boundary() -> None:
    time = pd.Series([1, 1, 1, 2, 2, 2, 3, 3, 4, 5])
    s = time_split(time, 0.5, 0.2)
    assert time[s.train].max() < time[s.valid].min()
    assert time[s.valid].max() < time[s.test].min()
    assert len(s.train) == 6  # the cut at row 5 pulls all rows with time 2 into train


def test_deterministic(time: pd.Series) -> None:
    a, b = time_split(time), time_split(time.sample(frac=1, random_state=7))
    assert a.train.sort_values().equals(b.train.sort_values())
    assert a.boundaries == b.boundaries


def test_boundaries_saved(time: pd.Series) -> None:
    d = time_split(time, 0.6, 0.2).to_dict()
    assert d["kind"] == "time"
    assert d["boundaries"]["train"] == {"min_time": 0, "max_time": 59}
    assert d["boundaries"]["test"] == {"min_time": 80, "max_time": 99}


def test_configurable_fractions(time: pd.Series) -> None:
    s = time_split(time, 0.7, 0.15)
    assert (len(s.train), len(s.valid), len(s.test)) == (70, 15, 15)


@pytest.mark.parametrize(("train", "valid"), [(0.0, 0.2), (0.8, 0.2), (0.6, 0.5), (1.2, 0.1)])
def test_bad_fractions(time: pd.Series, train: float, valid: float) -> None:
    with pytest.raises(SplitError):
        time_split(time, train, valid)


def test_too_few_timestamps() -> None:
    with pytest.raises(SplitError, match="empty"):
        time_split(pd.Series([1, 1, 1, 1, 2]))


def test_missing_time_rejected() -> None:
    with pytest.raises(SplitError, match="missing"):
        time_split(pd.Series([1.0, None, 3.0]))


def test_random_split_is_marked_and_rejected_by_guard(time: pd.Series) -> None:
    s = random_split(time.index, seed=3)
    assert s.kind == "random"
    assert len(s.train) + len(s.valid) + len(s.test) == 100
    with pytest.raises(SplitError, match="time split"):
        assert_no_time_overlap(s, time)


def test_overlap_detected(time: pd.Series) -> None:
    s = time_split(time)
    leaked = type(s)("time", s.train.append(s.test[:1]), s.valid, s.test[1:], s.boundaries)
    with pytest.raises(SplitError, match="overlaps"):
        assert_no_time_overlap(leaked, time)
