"""Tests for the rule-based baseline (T07)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.baselines.rule_based import RuleBasedBaseline, RuleConfigError
from fraud_risk.evaluation.split import time_split

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml"


@pytest.fixture
def rules() -> list[dict]:
    return yaml.safe_load(CONFIG.read_text())["rule_based"]["rules"]


def test_hand_example() -> None:
    X = pd.DataFrame({"amt": [1.0, 2, 3, 4, 100], "cat": ["a", "a", "b", "b", None]})
    y = pd.Series([0, 0, 1, 1, 0])
    model = RuleBasedBaseline(
        [
            {"name": "amt", "type": "numeric_above_quantile", "column": "amt", "quantile": 0.75},
            {
                "name": "cat",
                "type": "category_fraud_rate",
                "column": "cat",
                "rate_multiplier": 2.0,
                "min_count": 2,
            },
        ]
    ).fit(X, y)
    learned = model.describe()
    assert learned[0]["threshold"] == pytest.approx(4.0)
    assert learned[1]["risky_values"] == ["b"]  # rate 1.0 >= 2 x 0.4
    new = pd.DataFrame({"amt": [5.0, 1, np.nan], "cat": ["b", "a", "b"]})
    assert model.score(new).tolist() == [1.0, 0.0, 0.5]


def test_scores_in_unit_interval(ieee_dir: Path, rules: list[dict]) -> None:
    data = load_ieee_cis(ieee_dir)
    s = time_split(data.time)
    model = RuleBasedBaseline(rules).fit(data.X.loc[s.train], data.y.loc[s.train])
    scores = model.score(data.X.loc[s.valid])
    assert scores.min() >= 0 and scores.max() <= 1
    assert set(np.round(scores * 3)) <= {0, 1, 2, 3}  # three rules -> steps of 1/3


def test_thresholds_independent_of_validation_and_test(ieee_dir: Path, rules: list[dict]) -> None:
    data = load_ieee_cis(ieee_dir)
    s = time_split(data.time)
    X2, y2 = data.X.copy(), data.y.copy()
    holdout = s.valid.append(s.test)
    X2.loc[holdout, "TransactionAmt"] = 1e9
    X2.loc[holdout, "ProductCD"] = "W"
    y2.loc[holdout] = 1
    a = RuleBasedBaseline(rules).fit(data.X.loc[s.train], data.y.loc[s.train]).describe()
    b = RuleBasedBaseline(rules).fit(X2.loc[s.train], y2.loc[s.train]).describe()
    assert a == b


def test_thresholds_change_when_train_changes(ieee_dir: Path, rules: list[dict]) -> None:
    data = load_ieee_cis(ieee_dir)
    s = time_split(data.time)
    X2 = data.X.copy()
    X2.loc[s.train, "TransactionAmt"] *= 10
    a = RuleBasedBaseline(rules).fit(data.X.loc[s.train], data.y.loc[s.train]).describe()
    b = RuleBasedBaseline(rules).fit(X2.loc[s.train], data.y.loc[s.train]).describe()
    assert b[0]["threshold"] == pytest.approx(10 * a[0]["threshold"])


def test_config_rules_documented(rules: list[dict]) -> None:
    assert all(rule.get("description") for rule in rules)


def test_bad_rules() -> None:
    with pytest.raises(RuleConfigError):
        RuleBasedBaseline([])
    with pytest.raises(RuleConfigError):
        RuleBasedBaseline([{"name": "x", "type": "magic", "column": "a"}])
    with pytest.raises(RuleConfigError, match="quantile"):
        RuleBasedBaseline([{"name": "x", "type": "numeric_above_quantile", "column": "a"}])
    with pytest.raises(RuntimeError):
        RuleBasedBaseline(
            [{"name": "x", "type": "numeric_above_quantile", "column": "a", "quantile": 0.5}]
        ).score(pd.DataFrame({"a": [1]}))
