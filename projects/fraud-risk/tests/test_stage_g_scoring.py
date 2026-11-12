"""Stage G / G08: batch scorer gives the training scores, reads no label and no test period."""

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis, read_transactions
from fraud_risk.experiments import decision_data as dd
from fraud_risk.features.baseline_features import ROW_LOCAL_DERIVED, LabelLeakError
from fraud_risk.scoring import batch
from fraud_risk.scripts.config import ScoringConfig

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
OUT_COLUMNS = [
    "TransactionID", "score", "score_calibrated", "model_version", "feature_version",
    "execution_id",
]  # fmt: skip


@pytest.fixture(scope="module")
def data(ieee_dir_module: Path) -> Any:
    return load_ieee_cis(ieee_dir_module)


@pytest.fixture(scope="module")
def raw_cfg(data: Any, stage_g_raw: Any) -> dict:
    return stage_g_raw(data.time, "scoring.yaml")


@pytest.fixture(scope="module")
def cfg(raw_cfg: dict) -> ScoringConfig:
    return ScoringConfig.model_validate(raw_cfg)


@pytest.fixture(scope="module")
def dev(data: Any, cfg: ScoringConfig) -> dd.DevData:
    return dd.prepare(data.X, data.y, data.time, cfg)


@pytest.fixture(scope="module")
def scorer(dev: dd.DevData, cfg: ScoringConfig) -> batch.Scorer:
    return batch.build_scorer(dev, cfg, "score-test")


@pytest.fixture(scope="module")
def dev_input(ieee_dir_module: Path, dev: dd.DevData) -> pd.DataFrame:
    """Validation rows read back from the CSV file, label removed: what a caller would send."""
    rows = read_transactions(ieee_dir_module / "train_transaction.csv")
    rows = rows[rows["TransactionID"].isin(dev.valid)]
    return rows.drop(columns=["isFraud"]).reset_index(drop=True)


def test_real_config_is_draft_row_local_and_matches_gbm() -> None:
    raw = yaml.safe_load((CONFIGS / "scoring.yaml").read_text("utf-8"))
    parsed = ScoringConfig.model_validate(raw)
    assert parsed.status == "draft" and parsed.stage == "exploratory"
    assert parsed.scoring.calibration == "platt"
    assert set(parsed.features.derived) <= ROW_LOCAL_DERIVED
    gbm = yaml.safe_load((CONFIGS / "gbm.yaml").read_text("utf-8"))
    assert parsed.features.model_dump() == gbm["features"]


def test_batch_scores_equal_training_scores(
    scorer: batch.Scorer, dev: dd.DevData, dev_input: pd.DataFrame
) -> None:
    """Training-serving skew: same rows, scored from a CSV file, give the training scores."""
    out = batch.score_batch(scorer, dev_input, "exec-test")
    assert list(out.columns) == OUT_COLUMNS
    expected = dev.frame.loc[out["TransactionID"], "score_gbm"].to_numpy()
    np.testing.assert_array_equal(out["score"].to_numpy(), expected)
    np.testing.assert_array_equal(
        out["score_calibrated"].to_numpy(), scorer.calibrator.apply(expected)
    )
    assert (out["model_version"] == "score-test").all()
    assert (out["feature_version"] == scorer.feature_version).all()


def test_scores_do_not_depend_on_batch_order_or_size(
    scorer: batch.Scorer, dev_input: pd.DataFrame
) -> None:
    whole = batch.score_batch(scorer, dev_input, "e").set_index("TransactionID")
    shuffled = dev_input.sample(frac=1.0, random_state=1)
    cuts = [0, 7, len(shuffled) // 2, len(shuffled)]
    parts = [batch.score_batch(scorer, shuffled.iloc[a:b], "e") for a, b in pairwise(cuts)]
    joined = pd.concat(parts).set_index("TransactionID").loc[whole.index]
    pd.testing.assert_frame_equal(whole, joined)


def test_later_rows_do_not_change_earlier_scores(
    scorer: batch.Scorer, dev_input: pd.DataFrame
) -> None:
    """Look-ahead check: changing rows after a time t leaves the scores before t unchanged."""
    t = dev_input["TransactionDT"].median()
    changed = dev_input.copy()
    late = changed["TransactionDT"] > t
    changed.loc[late, "TransactionAmt"] = 1e6
    changed.loc[late, "C1"] = 99.0
    a = batch.score_batch(scorer, dev_input, "e")
    b = batch.score_batch(scorer, changed, "e")
    early = (dev_input["TransactionDT"] <= t).to_numpy()
    pd.testing.assert_frame_equal(a[early], b[early])
    assert not a[~early]["score"].equals(b[~early]["score"])  # the change did reach late rows


def test_label_in_input_is_refused(scorer: batch.Scorer, dev_input: pd.DataFrame) -> None:
    with pytest.raises(LabelLeakError):
        batch.score_batch(scorer, dev_input.assign(isFraud=0), "e")


def test_test_period_rows_are_refused(scorer: batch.Scorer, dev_input: pd.DataFrame) -> None:
    late = dev_input.head(3).copy()
    late.loc[late.index[0], "TransactionDT"] = scorer.last_dev_time + 1
    with pytest.raises(batch.TestPeriodError):
        batch.score_batch(scorer, late, "e")


def test_bad_ids_are_refused(scorer: batch.Scorer, dev_input: pd.DataFrame) -> None:
    with pytest.raises(batch.ScoringError):
        batch.score_batch(scorer, pd.concat([dev_input.head(2), dev_input.head(1)]), "e")
    with pytest.raises(batch.ScoringError):
        batch.score_batch(scorer, dev_input.drop(columns=["TransactionID"]), "e")


def test_history_features_are_refused(dev: dd.DevData, raw_cfg: dict) -> None:
    """History features need earlier rows of the entity; a batch scorer would get them wrong."""
    raw = {**raw_cfg, "features": {**raw_cfg["features"], "derived": ["card1_prev_count"]}}
    with pytest.raises(batch.ScoringError):
        batch.build_scorer(dev, ScoringConfig.model_validate(raw), "x")


def test_calibrator_uses_v1_labels_only(data: Any, cfg: ScoringConfig, dev: dd.DevData) -> None:
    """Flipping V2/V3 labels leaves the calibrator unchanged. Flipping V1 labels (sabotage)
    turns the Platt slope negative, and the scorer refuses that calibrator."""
    base = batch.build_scorer(dev, cfg, "x")

    def flipped(names: tuple[str, ...]) -> dd.DevData:
        y2 = data.y.copy()
        rows = dev.frame.index[dev.frame["block"].isin(names)]
        y2.loc[rows] = 1 - y2.loc[rows]
        return dd.prepare(data.X, y2, data.time, cfg)

    same = batch.build_scorer(flipped(("V2", "V3")), cfg, "x")
    assert same.calibrator.params == base.calibrator.params
    with pytest.raises(batch.ScoringError, match="not increasing"):
        batch.build_scorer(flipped(("V1",)), cfg, "x")


def test_train_and_score_cli(
    ieee_dir_module: Path, raw_cfg: dict, dev: dd.DevData, tmp_path: Path
) -> None:
    config = tmp_path / "scoring.yaml"
    config.write_text(yaml.safe_dump(raw_cfg), encoding="utf-8")
    manifest = ieee_dir_module.parent / "manifests" / "ieee-cis.yaml"
    args = ["--config", str(config), "--data-dir", str(ieee_dir_module),
            "--manifest", str(manifest), "--artifacts-dir", str(tmp_path / "a")]  # fmt: skip
    assert batch.main(["train", *args]) == 0
    model_dir = batch.latest_model_dir(tmp_path / "a")
    card = json.loads((model_dir / "model_card.json").read_text("utf-8"))
    assert card["model_version"] == model_dir.name and model_dir.name.startswith("score-")
    sample = read_transactions(model_dir / "sample_v3.csv")
    assert "isFraud" not in sample.columns
    assert set(sample["TransactionID"]) <= set(dev.frame.index[dev.frame["block"] == "V3"])

    assert batch.main(["score", "--artifacts-dir", str(tmp_path / "a")]) == 0
    [summary_path] = (tmp_path / "a" / "scores").glob("exec-*.json")
    summary = json.loads(summary_path.read_text("utf-8"))
    scored = pd.read_csv(summary_path.with_suffix(".csv"))
    assert list(scored.columns) == OUT_COLUMNS
    assert (scored["execution_id"] == summary_path.stem).all()
    assert summary["rows"] == len(sample) and summary["model_version"] == model_dir.name
    # Real-data skew check written by the scorer itself: rows also scored at training time.
    assert summary["skew_check"]["rows_compared"] == len(sample)
    assert summary["skew_check"]["max_abs_diff"] == 0.0

    first = (model_dir / "dev_scores.csv").read_bytes()
    assert batch.main(["train", *args]) == 0  # reproducible: same id, same training scores
    assert batch.latest_model_dir(tmp_path / "a") == model_dir
    assert (model_dir / "dev_scores.csv").read_bytes() == first
