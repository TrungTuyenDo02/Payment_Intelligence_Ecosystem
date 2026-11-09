"""Leakage guard tests (T10). Each guard is also shown to fail when it should.

Covered: (1) label-derived columns entering features, (2) a random split used by a
baseline, (3) a transformer or threshold fitted outside train.
Limitation: the label guard catches exact copies (or inverses) of the label and columns
named after it; a noisy proxy of the label is found by EDA step 6, not by this guard.
"""

import ast
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fraud_risk.adapters.ieee_cis import IeeeCisData, load_ieee_cis
from fraud_risk.baselines.logistic import LogisticBaseline
from fraud_risk.baselines.rule_based import RuleBasedBaseline
from fraud_risk.evaluation.split import Split, SplitError, random_split, time_split
from fraud_risk.features.baseline_features import LabelLeakError
from fraud_risk.features.guards import check_label_leakage
from fraud_risk.scripts.config import BaselineConfig, load_config
from fraud_risk.scripts.run_baseline import fit_baselines
from sklearn.pipeline import Pipeline

PACKAGE = Path(__file__).resolve().parents[1] / "fraud_risk"
CONFIG = Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml"


@pytest.fixture
def data(ieee_dir: Path) -> IeeeCisData:
    return load_ieee_cis(ieee_dir)


@pytest.fixture
def cfg() -> BaselineConfig:
    return load_config(CONFIG)[0]


# (1) Label-derived columns -----------------------------------------------------------


@pytest.mark.parametrize(
    "make_column",
    [
        lambda y: y.astype(float),
        lambda y: 1 - y,
        lambda y: y.map({0: "legit", 1: "fraud"}),
        lambda y: y * 100 + 5,
    ],
    ids=["copy", "inverse", "string_coded", "rescaled"],
)
def test_label_copy_rejected(
    make_column: Callable[[pd.Series], pd.Series], data: IeeeCisData
) -> None:
    features = pd.DataFrame({"C1": data.X["C1"], "leak": make_column(data.y)})
    with pytest.raises(LabelLeakError, match="reproduces the label"):
        check_label_leakage(features, data.y)


def test_label_named_column_rejected(data: IeeeCisData) -> None:
    features = pd.DataFrame({"isfraud_prev": np.zeros(len(data.y))}, index=data.y.index)
    with pytest.raises(LabelLeakError, match="named after the label"):
        check_label_leakage(features, data.y)


def test_honest_features_pass(data: IeeeCisData) -> None:
    check_label_leakage(data.X[["C1", "TransactionAmt", "ProductCD"]], data.y)


def test_misaligned_index_rejected(data: IeeeCisData) -> None:
    with pytest.raises(ValueError, match="same index"):
        check_label_leakage(data.X[["C1"]].iloc[1:], data.y)


def test_runner_rejects_label_derived_feature(data: IeeeCisData, cfg: BaselineConfig) -> None:
    X = data.X.assign(chargeback_flag=data.y.to_numpy())
    leaky = cfg.model_copy(deep=True)
    leaky.features.numeric.append("chargeback_flag")
    with pytest.raises(LabelLeakError):
        fit_baselines(X, data.y, data.time, time_split(data.time), leaky)


def test_x_never_contains_label(data: IeeeCisData) -> None:
    assert "isFraud" not in data.X.columns


# (2) Random split ----------------------------------------------------------------------


def test_runner_rejects_random_split(data: IeeeCisData, cfg: BaselineConfig) -> None:
    leaky = random_split(data.X.index, seed=0)
    with pytest.raises(SplitError):
        fit_baselines(data.X, data.y, data.time, leaky, cfg)


def test_runner_rejects_time_split_with_overlap(data: IeeeCisData, cfg: BaselineConfig) -> None:
    s = time_split(data.time)
    tampered = Split("time", s.train.append(s.test[:5]), s.valid, s.test[5:], s.boundaries)
    with pytest.raises(SplitError, match="overlaps"):
        fit_baselines(data.X, data.y, data.time, tampered, cfg)


# Modules allowed to use the leaky split besides split.py: the Stage E experiments that measure
# how much it changes the score (validation only, never a model for test).
RANDOM_SPLIT_ALLOWED = {
    "evaluation/split.py",
    "experiments/leakage.py",
    "experiments/split_diagnostics.py",
}


def test_random_split_only_defined_in_split_module() -> None:
    """No module except split.py and the leakage experiment may use random_split (static check)."""
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        if path.relative_to(PACKAGE).as_posix() in RANDOM_SPLIT_ALLOWED:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.Attribute | ast.Name):
                names = [getattr(node, "attr", None) or getattr(node, "id", None)]
            if "random_split" in names:
                offenders.append(str(path.relative_to(PACKAGE)))
    assert offenders == []


# (3) Fitting outside train ---------------------------------------------------------------


def _record_fits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, pd.Index]]:
    records: list[tuple[str, pd.Index]] = []
    pipeline_fit, rules_fit = Pipeline.fit, RuleBasedBaseline.fit

    def spy_pipeline(self: Pipeline, X: pd.DataFrame, *a: object, **k: object) -> Pipeline:
        records.append(("pipeline", X.index))
        return pipeline_fit(self, X, *a, **k)

    def spy_rules(self: RuleBasedBaseline, X: pd.DataFrame, y: pd.Series) -> RuleBasedBaseline:
        records.append(("rules", X.index))
        return rules_fit(self, X, y)

    monkeypatch.setattr(Pipeline, "fit", spy_pipeline)
    monkeypatch.setattr(RuleBasedBaseline, "fit", spy_rules)
    return records


def _assert_fitted_on_train_only(records: list[tuple[str, pd.Index]], split: Split) -> None:
    assert {kind for kind, _ in records} == {"pipeline", "rules"}
    for kind, index in records:
        assert index.equals(split.train), f"{kind} was fitted on rows outside train"


def test_all_fits_use_train_only(
    data: IeeeCisData, cfg: BaselineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    split = time_split(data.time)
    records = _record_fits(monkeypatch)
    fitted = fit_baselines(data.X, data.y, data.time, split, cfg)
    _assert_fitted_on_train_only(records, split)
    assert fitted["logistic"]["model"].fit_index_.equals(split.train)
    assert fitted["rule_based"]["model"].fit_index_.equals(split.train)


def test_fit_guard_catches_fit_on_all_rows(
    data: IeeeCisData, cfg: BaselineConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard must fail for the classic mistake: fitting the scaler/model on all rows."""
    split = time_split(data.time)
    records = _record_fits(monkeypatch)
    RuleBasedBaseline(cfg.rule_based.rules).fit(data.X, data.y)
    features = data.X[["C1", "C2"]]
    LogisticBaseline(["C1", "C2"], [], seed=0).fit(features, data.y)
    with pytest.raises(AssertionError, match="outside train"):
        _assert_fitted_on_train_only(records, split)


def test_scores_do_not_depend_on_holdout_rows(data: IeeeCisData, cfg: BaselineConfig) -> None:
    """Changing validation/test rows must not change fitted models (train scores identical)."""
    split = time_split(data.time)
    X2, y2 = data.X.copy(), data.y.copy()
    holdout = split.valid.append(split.test)
    X2.loc[holdout, ["TransactionAmt", "C1"]] = 1e6
    y2.loc[holdout] = 1 - y2.loc[holdout]
    a = fit_baselines(data.X, data.y, data.time, split, cfg)
    b = fit_baselines(X2, y2, data.time, split, cfg)
    for model in ("rule_based", "logistic"):
        assert np.array_equal(a[model]["scores"]["train"], b[model]["scores"]["train"])
