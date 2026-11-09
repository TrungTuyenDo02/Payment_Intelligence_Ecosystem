"""Open question 1: random vs time split diagnostics never read test rows."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.evaluation.split import time_split
from fraud_risk.experiments import split_diagnostics as sd
from fraud_risk.scripts.config import LeakageConfig

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def test_reweighting_to_own_prevalence_changes_nothing() -> None:
    y = pd.Series([0, 0, 0, 1, 0, 1, 0, 0])
    scores = np.array([0.1, 0.4, 0.2, 0.9, 0.3, 0.6, 0.5, 0.05])
    plain = sd.pr_auc(y, scores)
    assert sd.reweighted_pr_auc(y, scores, float(y.mean())) == pytest.approx(plain)


def test_reweighting_matches_hand_computation() -> None:
    # Positive ranked 2nd of 3: unweighted AP = 1/2. Doubling the positive's odds
    # (prevalence 1/3 -> 1/2) gives precision 2/(2+1) = 2/3 at the positive's rank.
    y = pd.Series([0, 1, 0])
    scores = np.array([0.9, 0.8, 0.1])
    assert sd.reweighted_pr_auc(y, scores, 0.5) == pytest.approx(2 / 3)


@pytest.fixture(scope="module")
def data(ieee_dir_module: Path) -> Any:
    return load_ieee_cis(ieee_dir_module)


def _cfg() -> LeakageConfig:
    raw = yaml.safe_load((CONFIGS / "leakage.yaml").read_text("utf-8"))
    return LeakageConfig.model_validate(raw)


def test_diagnostics_never_use_test_rows_or_labels(data: Any) -> None:
    cfg = _cfg()
    split = time_split(data.time, 0.6, 0.2)
    flipped = data.y.copy()
    flipped.loc[split.test] = 1 - flipped.loc[split.test]
    first = sd.run_diagnostics(data.X, data.y, data.time, cfg)
    second = sd.run_diagnostics(data.X, flipped, data.time, cfg)
    assert first == second
    assert first["pre_test_rows"] == len(split.train) + len(split.valid)
    assert set(first["matrix"]) == {
        f"train_{m}__valid_{v}" for m in ("time", "random") for v in ("time", "random")
    }


def test_paired_bootstrap_is_zero_for_equal_scores_and_seeded() -> None:
    rng = np.random.default_rng(0)
    y = pd.Series((rng.random(400) < 0.2).astype(int))
    good = y.to_numpy() * 0.5 + rng.random(400)
    weak = rng.random(400)
    same = sd.paired_bootstrap_diff(y, good, good, n_resamples=50, seed=1)
    assert same == {"diff": 0.0, "low": 0.0, "high": 0.0}
    first = sd.paired_bootstrap_diff(y, good, weak, n_resamples=50, seed=1)
    assert first == sd.paired_bootstrap_diff(y, good, weak, n_resamples=50, seed=1)
    assert first["low"] > 0  # a clearly better ranking is better on every resample


def test_paired_bootstrap_accepts_another_metric() -> None:
    y = pd.Series([0, 1] * 50)
    a = y.to_numpy() * 1.0
    b = 1 - a  # perfectly wrong ranking
    top = sd.paired_bootstrap_diff(
        y, a, b, n_resamples=20, seed=0, metric=lambda yt, s: float(s[yt == 1].mean())
    )
    assert top["diff"] == 1.0
