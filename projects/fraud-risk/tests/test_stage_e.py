"""Stage E: target encoding, entity overlap, leakage experiment and Gradient Boosting runner.

All on the small synthetic IEEE-CIS-shaped fixture (no real data).
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.evaluation.entity_overlap import entity_key, entity_overlap
from fraud_risk.evaluation.run_log import AlreadyEvaluatedOnTestError
from fraud_risk.evaluation.split import time_split
from fraud_risk.experiments import leakage
from fraud_risk.features.baseline_features import FeatureSpec, build_features
from fraud_risk.features.target_encoding import TargetEncoder
from fraud_risk.models.gbm import GbmModel, param_grid
from fraud_risk.scripts import run_gbm
from fraud_risk.scripts.config import LeakageConfig
from fraud_risk.scripts.run_baseline import ConfigNotFrozenError

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


# --- target encoding ---


def test_target_encoding_matches_hand_computation() -> None:
    values = pd.Series(["a", "a", "a", "b"], index=[10, 11, 12, 13])
    y = pd.Series([1, 1, 0, 0], index=values.index)
    enc = TargetEncoder(smoothing=2).fit(values, y)
    # prior 0.5; a: (2 + 2*0.5) / (3 + 2) = 0.6; b: (0 + 1) / (1 + 2) = 1/3; unseen -> prior
    out = enc.transform(pd.Series(["a", "b", "zzz", None]))
    np.testing.assert_allclose(out.to_numpy(), [0.6, 1 / 3, 0.5, 0.5])


def test_target_encoding_uses_only_the_rows_it_is_fitted_on() -> None:
    values = pd.Series(["a", "a", "b", "b"])
    y = pd.Series([0, 0, 1, 1])
    first = TargetEncoder(0).fit(values.iloc[:2], y.iloc[:2])
    assert first.fit_index_.equals(values.index[:2])
    assert first.transform(pd.Series(["b"])).iloc[0] == 0.0  # b unseen -> prior of fitted rows


# --- entity overlap ---


def test_entity_overlap_counts_seen_cards_and_hides_test_labels() -> None:
    X = pd.DataFrame({"card1": [1, 2, 3, 1, 4, 2, 9], "addr1": [5, 5, 5, 5, 5, None, 5]})
    y = pd.Series([0, 1, 0, 1, 0, 0, 1])
    time = pd.Series(range(7))
    split = time_split(time, 3 / 7, 2 / 7)  # train rows 0-2, valid 3-4, test 5-6
    rows = entity_overlap(X, y, split, [["card1"], ["card1", "addr1"]])
    valid_card = next(r for r in rows if r["key"] == "card1" and r["part"] == "valid")
    assert valid_card["share_seen_in_train"] == 0.5  # card 1 seen, card 4 new
    assert (valid_card["fraud_rate_seen"], valid_card["fraud_rate_new"]) == (1.0, 0.0)
    test_pair = next(r for r in rows if r["key"] == "card1+addr1" and r["part"] == "test")
    assert test_pair["rows_with_key"] == 1  # row 5 has no addr1
    assert test_pair["fraud_rate_seen"] is None and test_pair["fraud_rate_new"] is None
    assert entity_key(X, ["card1", "addr1"]).isna().sum() == 1


# --- leakage experiment ---


def _leak_cfg() -> LeakageConfig:
    raw = yaml.safe_load((CONFIGS / "leakage.yaml").read_text("utf-8"))
    raw["metrics"]["bootstrap_resamples"] = 20
    raw["entity_overlap"]["keys"] = [["card1"], ["card1", "P_emaildomain"]]  # fixture: no addr1
    return LeakageConfig.model_validate(raw)


@pytest.fixture(scope="module")
def fixture_data(ieee_dir_module: Path) -> Any:
    return ieee_dir_module, load_ieee_cis(ieee_dir_module)


def test_leakage_variants_are_scored_on_validation_only(fixture_data: Any) -> None:
    _, data = fixture_data
    cfg = _leak_cfg()
    result = leakage.run_experiment(data.X, data.y, data.time, cfg)
    names = set(result["variants"])
    assert names == {"proper", "random_split", "preprocess_on_all", "target_enc_train",
                     "target_enc_leaky", "gap_7d", "gap_14d"}  # fmt: skip
    n_valid = len(time_split(data.time, 0.6, 0.2).valid)
    for name, v in result["variants"].items():
        assert v["rows"] == n_valid, name  # every variant: same number of validation rows
    assert result["variants"]["proper"]["pr_auc_minus_proper"] == 0
    assert result["variants"]["gap_14d"]["train_rows"] < result["variants"]["gap_7d"]["train_rows"]


def test_leaky_target_encoding_inflates_the_score(fixture_data: Any) -> None:
    """card1 is almost unique per row in the fixture: validation labels leak straight in."""
    _, data = fixture_data
    v = leakage.run_experiment(data.X, data.y, data.time, _leak_cfg())["variants"]
    assert v["target_enc_leaky"]["pr_auc"] > v["target_enc_train"]["pr_auc"] + 0.2


def test_test_labels_never_change_the_experiment(fixture_data: Any) -> None:
    _, data = fixture_data
    cfg = _leak_cfg()
    test_rows = time_split(data.time, 0.6, 0.2).test
    flipped = data.y.copy()
    flipped.loc[test_rows] = 1 - flipped.loc[test_rows]
    first = leakage.run_experiment(data.X, data.y, data.time, cfg)
    second = leakage.run_experiment(data.X, flipped, data.time, cfg)
    for name in first["variants"]:
        if name != "random_split":  # a random split mixes test-period rows into train on purpose
            assert first["variants"][name] == second["variants"][name], name
    assert first["entity_overlap"] == second["entity_overlap"]


def test_leakage_run_writes_folder_and_summary(fixture_data: Any, tmp_path: Path) -> None:
    directory, _ = fixture_data
    raw = yaml.safe_load((CONFIGS / "leakage.yaml").read_text("utf-8"))
    raw["metrics"]["bootstrap_resamples"] = 20
    raw["entity_overlap"]["keys"] = [["card1"]]
    config = tmp_path / "leakage.yaml"
    config.write_text(yaml.safe_dump(raw, sort_keys=False))
    manifest = directory.parent / "manifests" / "ieee-cis.yaml"
    out = leakage.run(config, data_dir=directory, manifest_path=manifest,
                      artifacts_dir=tmp_path / "artifacts")  # fmt: skip
    assert out.name.startswith("leak-")
    results = json.loads((out / "results.json").read_text())
    assert results["evaluated_on"] == "valid"
    summary = (out / "summary.md").read_text("utf-8")
    assert "Chia ngẫu nhiên" in summary and "không đọc nhãn test" in summary


# --- Gradient Boosting ---


def test_param_grid_is_every_combination_in_fixed_order() -> None:
    grid = param_grid({"max_iter": [10, 20], "learning_rate": [0.1]})
    assert grid == [{"learning_rate": 0.1, "max_iter": 10}, {"learning_rate": 0.1, "max_iter": 20}]


def test_gbm_fits_on_train_only_and_handles_unseen_categories(fixture_data: Any) -> None:
    _, data = fixture_data
    cols = {"numeric": ["TransactionAmt", "C1"], "categorical": ["ProductCD"]}
    spec = FeatureSpec.from_config({**cols, "derived": ["log_amount"]})
    features = build_features(data.X, spec)
    split = time_split(data.time, 0.6, 0.2)
    model = GbmModel(spec.numeric_out, spec.categorical_out, seed=0, params={"max_iter": 20})
    model.fit(features.loc[split.train], data.y.loc[split.train])
    assert model.fit_index_.equals(split.train)
    unseen = features.loc[split.valid].copy()
    unseen["ProductCD"] = "never-seen"
    scores = model.score(unseen)
    assert np.isfinite(scores).all() and ((scores >= 0) & (scores <= 1)).all()


def _gbm_config(tmp_path: Path, status: str = "draft", gap: float = 0) -> Path:
    raw = yaml.safe_load((CONFIGS / "gbm.yaml").read_text("utf-8"))
    raw["status"] = status
    raw["metrics"]["bootstrap_resamples"] = 20
    raw["split"]["gap_days"] = gap
    raw["gbm"]["grid"] = {"max_iter": [20, 40], "learning_rate": [0.1]}
    path = tmp_path / f"gbm-{status}-{gap}.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def _gbm_run(
    directory: Path, config: Path, artifacts: Path, stage: str, force: bool = False
) -> Path:
    manifest = directory.parent / "manifests" / "ieee-cis.yaml"
    return run_gbm.run(config, stage, data_dir=directory, manifest_path=manifest,
                       artifacts_dir=artifacts, force=force)  # fmt: skip


def test_gbm_validation_run_is_reproducible_and_keeps_test_closed(
    fixture_data: Any, tmp_path: Path
) -> None:
    directory, _ = fixture_data
    config = _gbm_config(tmp_path)
    first = _gbm_run(directory, config, tmp_path / "a", "validation")
    second = _gbm_run(directory, config, tmp_path / "b", "validation")
    assert (first / "metrics.json").read_bytes() == (second / "metrics.json").read_bytes()
    metrics = json.loads((first / "metrics.json").read_text())
    assert set(metrics["models"]["gbm"]) == {"train", "valid"}  # no test numbers
    models = json.loads((first / "models.json").read_text())["gbm"]
    assert len(models["grid"]) == 2 and models["chosen_on"] == "valid"
    best = max(g["valid_pr_auc"] for g in models["grid"])
    assert metrics["models"]["gbm"]["valid"]["pr_auc"] == pytest.approx(best)


def test_gbm_final_needs_frozen_and_runs_once(fixture_data: Any, tmp_path: Path) -> None:
    directory, _ = fixture_data
    with pytest.raises(ConfigNotFrozenError):
        _gbm_run(directory, _gbm_config(tmp_path, "draft"), tmp_path / "art", "final")
    frozen = _gbm_config(tmp_path, "frozen")
    out = _gbm_run(directory, frozen, tmp_path / "art", "final")
    assert (
        out.name == "test"
        and "test" in json.loads((out / "metrics.json").read_text())["models"]["gbm"]
    )
    with pytest.raises(AlreadyEvaluatedOnTestError):
        _gbm_run(directory, frozen, tmp_path / "art", "final")


def test_gap_gives_a_new_run_id(fixture_data: Any, tmp_path: Path) -> None:
    directory, _ = fixture_data
    plain = _gbm_run(directory, _gbm_config(tmp_path, gap=0), tmp_path / "art", "validation")
    gapped = _gbm_run(directory, _gbm_config(tmp_path, gap=7), tmp_path / "art", "validation")
    assert plain.name != gapped.name
    rows = json.loads((gapped / "split.json").read_text())["rows"]
    assert rows["gap_excluded"] > 0


def test_out_of_fold_encoding_never_uses_a_rows_own_label() -> None:
    from fraud_risk.features.target_encoding import encode_out_of_fold

    values = pd.Series(["a"] * 4 + ["b"] * 4)
    y = pd.Series([1, 1, 0, 0, 1, 1, 0, 0])
    order = pd.Series(range(8))
    out = encode_out_of_fold(values, y, order, n_folds=2, smoothing=0)
    # block 1 (rows 0-3, all "a") is encoded from rows 4-7, where "a" never appears -> prior 0.5
    assert (out.iloc[:4] == 0.5).all()
    flipped = y.copy()
    flipped.iloc[0] = 0  # a row's own label must not change its own encoding
    again = encode_out_of_fold(values, flipped, order, n_folds=2, smoothing=0)
    assert again.iloc[0] == out.iloc[0]


@pytest.mark.parametrize("main", [leakage.main, run_gbm.main])
def test_missing_dataset_gives_a_clear_message(
    main: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--data-dir", str(tmp_path / "nowhere")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("ERROR:") and "Traceback" not in err


def test_cli_runs_end_to_end(fixture_data: Any, tmp_path: Path) -> None:
    directory, _ = fixture_data
    manifest = directory.parent / "manifests" / "ieee-cis.yaml"
    common = ["--data-dir", str(directory), "--manifest", str(manifest)]
    config = _gbm_config(tmp_path)
    assert run_gbm.main(["--config", str(config), *common, "--artifacts-dir", str(tmp_path)]) == 0
