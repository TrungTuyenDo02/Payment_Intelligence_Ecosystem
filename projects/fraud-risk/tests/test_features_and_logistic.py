"""Tests for baseline features and the logistic baseline (T08)."""

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.baselines.logistic import LogisticBaseline
from fraud_risk.evaluation.metrics import select_threshold
from fraud_risk.evaluation.split import Split, time_split
from fraud_risk.features.baseline_features import (
    FeatureSpec,
    FeatureSpecError,
    LabelLeakError,
    build_features,
)
from sklearn.pipeline import Pipeline

Prepared = tuple[pd.DataFrame, pd.Series, Split]
CONFIG = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml").read_text()
)


@pytest.fixture
def spec() -> FeatureSpec:
    return FeatureSpec.from_config(CONFIG["features"])


@pytest.fixture
def prepared(ieee_dir: Path, spec: FeatureSpec) -> Prepared:
    data = load_ieee_cis(ieee_dir)
    split = time_split(data.time)
    return build_features(data.X, spec), data.y, split


def _model(spec: FeatureSpec, seed: int = 42) -> LogisticBaseline:
    return LogisticBaseline(spec.numeric_out, spec.categorical_out, seed=seed)


def test_starter_feature_list(spec: FeatureSpec) -> None:
    assert spec.numeric == ("TransactionAmt", *[f"C{i}" for i in range(1, 15)])
    assert spec.categorical == ("ProductCD", "card4", "card6")
    assert spec.derived == ("log_amount", "hour_of_day")


def test_derived_features() -> None:
    X = pd.DataFrame({"TransactionAmt": [0.0, np.e - 1], "TransactionDT": [86_400, 90_000]})
    out = build_features(X, FeatureSpec((), (), ("log_amount", "hour_of_day")))
    assert out["log_amount"].tolist() == pytest.approx([0.0, 1.0])
    assert out["hour_of_day"].tolist() == [0.0, 1.0]


def test_build_features_has_no_label_parameter() -> None:
    assert "y" not in inspect.signature(build_features).parameters


@pytest.mark.parametrize(
    "cfg",
    [
        {"numeric": ["TransactionID"]},
        {"numeric": ["TransactionDT"]},
        {"numeric": ["isFraud"]},
        {"numeric": ["isFraud_rolling"]},
        {"numeric": ["C1", "C1"]},
        {"derived": ["future_amount"]},
        {},
    ],
)
def test_invalid_specs(cfg: dict) -> None:
    with pytest.raises(FeatureSpecError):
        FeatureSpec.from_config(cfg)


def test_label_in_input_rejected(ieee_dir: Path, spec: FeatureSpec) -> None:
    data = load_ieee_cis(ieee_dir)
    with pytest.raises(LabelLeakError):
        build_features(data.X.assign(isFraud=data.y), spec)


def test_missing_column_clear_error(ieee_dir: Path, spec: FeatureSpec) -> None:
    X = load_ieee_cis(ieee_dir).X.drop(columns=["card4"])
    with pytest.raises(FeatureSpecError, match="card4"):
        build_features(X, spec)


def test_pipeline_fit_on_train_only(
    prepared: Prepared, spec: FeatureSpec, monkeypatch: pytest.MonkeyPatch
) -> None:
    features, y, split = prepared
    seen: list[pd.Index] = []
    original = Pipeline.fit

    def spy(self: Pipeline, X: pd.DataFrame, *args: object, **kwargs: object) -> Pipeline:
        seen.append(X.index)
        return original(self, X, *args, **kwargs)

    monkeypatch.setattr(Pipeline, "fit", spy)
    model = _model(spec).fit(features.loc[split.train], y.loc[split.train])
    assert seen and all(idx.equals(split.train) for idx in seen)
    # The scaler's learned means are exactly the train medians-imputed means.
    scaler = model.pipeline_.named_steps["prep"].named_transformers_["num"].named_steps["scale"]
    train_num = features.loc[split.train, spec.numeric_out]
    expected = train_num.fillna(train_num.median()).mean().to_numpy()
    assert scaler.mean_ == pytest.approx(expected)


def test_threshold_from_validation_and_deterministic(prepared: Prepared, spec: FeatureSpec) -> None:
    features, y, split = prepared
    a = _model(spec).fit(features.loc[split.train], y.loc[split.train])
    b = _model(spec).fit(features.loc[split.train], y.loc[split.train])
    sa, sb = a.score(features.loc[split.valid]), b.score(features.loc[split.valid])
    assert np.array_equal(sa, sb)
    assert ((sa >= 0) & (sa <= 1)).all()
    threshold = select_threshold(y.loc[split.valid], sa, CONFIG["metrics"]["threshold_method"])
    assert sa.min() <= threshold <= sa.max()
    assert "C1" in " ".join(a.describe()["coefficients"])


def test_unseen_category_ignored(prepared: Prepared, spec: FeatureSpec) -> None:
    features, y, split = prepared
    model = _model(spec).fit(features.loc[split.train], y.loc[split.train])
    unseen = features.loc[split.valid].assign(ProductCD="NEVER_SEEN")
    assert np.isfinite(model.score(unseen)).all()


def test_high_cardinality_rejected(prepared: Prepared) -> None:
    features, y, split = prepared
    wide = features.assign(card1_cat=[str(i) for i in range(len(features))])
    with pytest.raises(ValueError, match="high-cardinality"):
        LogisticBaseline(["C1"], ["card1_cat"], seed=0).fit(
            wide.loc[split.train], y.loc[split.train]
        )


def test_card_history_uses_only_earlier_transactions():
    # Rows out of time order on purpose; card 1 has amounts 10, 30, 20 at t=0, 50, 100.
    X = pd.DataFrame(
        {
            "card1": [1, 2, 1, 1],
            "TransactionAmt": [20.0, 5.0, 10.0, 30.0],
            "TransactionDT": [100, 10, 0, 50],
        },
        index=[7, 8, 9, 10],
    )
    spec = FeatureSpec(
        numeric=(),
        categorical=(),
        derived=("card1_prev_count", "card1_amt_vs_mean", "card1_secs_since_prev"),
    )
    f = build_features(X, spec)
    assert f["card1_prev_count"].tolist() == [2, 0, 0, 1]
    assert f.loc[7, "card1_amt_vs_mean"] == 20.0 / 20.0  # mean of 10 and 30
    assert f.loc[10, "card1_amt_vs_mean"] == 3.0
    assert f[["card1_amt_vs_mean", "card1_secs_since_prev"]].loc[[8, 9]].isna().all().all()
    assert f.loc[7, "card1_secs_since_prev"] == 50

    # Changing the latest transaction must not change any earlier row's features.
    later = X.copy()
    later.loc[7, "TransactionAmt"] = 9999.0
    g = build_features(later, spec)
    pd.testing.assert_frame_equal(f.drop(index=7), g.drop(index=7))


def test_windowed_counts_look_back_only_and_stay_on_one_scale():
    # Card 1 at t = 0, 3600, 90000, 90000 (a tie), 700000; 24h = 86400 s, 7d = 604800 s.
    X = pd.DataFrame(
        {"card1": [1, 1, 1, 1, 1, 2], "TransactionDT": [0, 3600, 90000, 90000, 650000, 5]},
    )
    spec = FeatureSpec(numeric=(), categorical=(), derived=("card1_count_24h", "card1_count_7d"))
    f = build_features(X, spec)
    # t=90000: the first row (0) is 90000 s ago, outside 24h; 3600 is inside. The tie counts
    # the earlier-listed row only. t=650000: only the two rows at 90000 are within 7 days.
    assert f["card1_count_24h"].tolist() == [0, 1, 1, 2, 0, 0]
    assert f["card1_count_7d"].tolist() == [0, 1, 2, 3, 2, 0]
    later = X.copy()
    later.loc[4, "TransactionDT"] = 800000  # moving the latest row must not change earlier rows
    g = build_features(later, spec)
    pd.testing.assert_frame_equal(f.drop(index=4), g.drop(index=4))
