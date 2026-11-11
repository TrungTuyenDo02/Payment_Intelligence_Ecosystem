"""Stage G / G03: calibration on V1 only, test rows never read, wrong-role blocks rejected."""

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.evaluation.split import DAY_SECONDS, time_split
from fraud_risk.experiments import calibration as cal
from fraud_risk.experiments import decision_data as dd
from fraud_risk.scripts.config import CalibrationConfig

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def synthetic_raw(time: pd.Series, base: str = "calibration.yaml") -> dict[str, Any]:
    """The real Stage G config with blocks re-cut for the synthetic validation days."""
    raw = yaml.safe_load((CONFIGS / base).read_text("utf-8"))
    split = time_split(time, raw["split"]["train_frac"], raw["split"]["valid_frac"])
    days = sorted(int(d) for d in (time.loc[split.valid] // DAY_SECONDS).unique())
    a, b = days[len(days) // 3], days[2 * len(days) // 3]
    raw["blocks"] = {"V1": [days[0], a - 1], "V2": [a, b - 1], "V3": [b, days[-1]]}
    raw["check"] = {}  # synthetic data: no Stage E numbers to reproduce
    raw["models"]["gbm"] = {"learning_rate": 0.1, "max_iter": 30, "max_leaf_nodes": 7}
    return raw


@pytest.fixture(scope="module")
def data(ieee_dir_module: Path) -> Any:
    return load_ieee_cis(ieee_dir_module)


@pytest.fixture(scope="module")
def cfg(data: Any) -> CalibrationConfig:
    return CalibrationConfig.model_validate(synthetic_raw(data.time))


@pytest.fixture(scope="module")
def dev(data: Any, cfg: CalibrationConfig) -> dd.DevData:
    return dd.prepare(data.X, data.y, data.time, cfg)


def test_real_config_is_draft_and_exploratory() -> None:
    raw = yaml.safe_load((CONFIGS / "calibration.yaml").read_text("utf-8"))
    parsed = CalibrationConfig.model_validate(raw)
    assert parsed.status == "draft" and parsed.stage == "exploratory"
    assert parsed.blocks.model_dump() == {"V1": (101, 113), "V2": (114, 126), "V3": (127, 141)}
    assert "isotonic" not in raw["calibration"]["methods"]  # D5


def test_dev_data_has_no_test_rows(data: Any, cfg: CalibrationConfig, dev: dd.DevData) -> None:
    split = time_split(data.time, 0.6, 0.2)
    assert not dev.frame.index.isin(split.test).any()
    assert len(dev.frame) == len(split.train) + len(split.valid)


def test_test_rows_change_nothing(data: Any, cfg: CalibrationConfig, dev: dd.DevData) -> None:
    split = time_split(data.time, 0.6, 0.2)
    y2, X2 = data.y.copy(), data.X.copy()
    y2.loc[split.test] = 1 - y2.loc[split.test]
    X2.loc[split.test, "TransactionAmt"] = 1e6
    X2.loc[split.test, "C1"] = -5.0
    other = dd.prepare(X2, y2, data.time, cfg)
    pd.testing.assert_frame_equal(dev.frame, other.frame)
    assert cal.run_calibration(dev, cfg) == cal.run_calibration(other, cfg)


def test_blocks_tile_validation_with_roles(dev: dd.DevData) -> None:
    found = dd.blocks(dev)
    assert [b.role for b in found.values()] == ["calibrate", "select", "evaluate"]
    joined = found["V1"].index.append(found["V2"].index).append(found["V3"].index)
    assert sorted(joined) == sorted(dev.valid)
    days = {n: dev.frame.loc[b.index, "day"] for n, b in found.items()}
    assert days["V1"].max() < days["V2"].min() and days["V2"].max() < days["V3"].min()


def test_calibrator_refuses_select_or_evaluate_block(dev: dd.DevData) -> None:
    """Sabotage: fitting on V3 (or V2) must fail loudly."""
    found = dd.blocks(dev)
    for name in ("V2", "V3"):
        with pytest.raises(dd.BlockRoleError):
            cal.fit_calibrator("platt", dev, "gbm", found[name])


def test_prior_shift_undoes_balanced_weights() -> None:
    # Balanced weights multiply the odds by n0/n1; at prior 0.2 a weighted 0.5 means 0.2.
    assert cal.prior_shift(np.array([0.5]), 0.2)[0] == pytest.approx(0.2)


def test_monotone_calibration_keeps_pr_auc(dev: dd.DevData, cfg: CalibrationConfig) -> None:
    result = cal.run_calibration(dev, cfg)
    for model in ("gbm", "logistic"):
        aps = {m: r["blocks"]["V3"]["pr_auc"] for m, r in result["models"][model].items()
               if m != "chosen" and r["monotone"]}  # fmt: skip
        assert {"raw", "prior_shift"} <= set(aps)
        assert max(aps.values()) - min(aps.values()) < 1e-9


def test_v3_labels_do_not_change_fit_or_choice(dev: dd.DevData, cfg: CalibrationConfig) -> None:
    frame = dev.frame.copy()
    v3 = frame["block"] == "V3"
    frame.loc[v3, "y"] = 1 - frame.loc[v3, "y"]
    flipped = dd.DevData(**{**dev.__dict__, "frame": frame})
    a, b = cal.run_calibration(dev, cfg), cal.run_calibration(flipped, cfg)
    for model in ("gbm", "logistic"):
        assert a["models"][model]["chosen"] == b["models"][model]["chosen"]
        for method in cfg.calibration.methods:
            assert a["models"][model][method]["params"] == b["models"][model][method]["params"]


def test_brier_and_log_loss_match_pure_python() -> None:
    rng = np.random.default_rng(1)
    y = (rng.random(1000) < 0.04).astype(int)
    p = np.clip(rng.beta(1, 20, 1000) + 0.1 * y, 1e-6, 1 - 1e-6)
    brier = sum((pi - yi) ** 2 for pi, yi in zip(p, y, strict=True)) / len(y)
    loss = -sum(yi * math.log(pi) + (1 - yi) * math.log(1 - pi)
                for pi, yi in zip(p, y, strict=True)) / len(y)  # fmt: skip
    got = cal.calibration_metrics(y, p, bins=10)
    assert got["brier"] == pytest.approx(brier) and got["log_loss"] == pytest.approx(loss)
    assert sum(b["rows"] for b in got["reliability"]) == 1000


def test_permuted_v3_labels_fall_to_chance(dev: dd.DevData, cfg: CalibrationConfig) -> None:
    checks = cal.run_calibration(dev, cfg)["self_checks"]
    assert abs(checks["permuted_v3_pr_auc"] - checks["v3_prevalence"]) < 0.05


def test_reproduction_check_stops_a_different_model(data: Any) -> None:
    raw = synthetic_raw(data.time)
    raw["check"] = {"gbm_valid_pr_auc": 0.999}
    with pytest.raises(dd.ReproductionError):
        dd.prepare(data.X, data.y, data.time, CalibrationConfig.model_validate(raw))


def test_blocks_must_cover_validation(data: Any) -> None:
    raw = synthetic_raw(data.time)
    raw["blocks"]["V3"][1] -= 1
    with pytest.raises(ValueError, match="cover"):
        dd.prepare(data.X, data.y, data.time, CalibrationConfig.model_validate(raw))


def test_runner_is_reproducible(ieee_dir_module: Path, data: Any, tmp_path: Path) -> None:
    config = tmp_path / "cal.yaml"
    config.write_text(yaml.safe_dump(synthetic_raw(data.time)), encoding="utf-8")
    manifest = ieee_dir_module.parent / "manifests" / "ieee-cis.yaml"
    outs = [
        cal.run(
            config,
            data_dir=ieee_dir_module,
            manifest_path=manifest,
            artifacts_dir=tmp_path / f"a{i}",
        )  # fmt: skip
        for i in range(2)
    ]
    assert outs[0].name == outs[1].name and outs[0].name.startswith("cal-")
    results = [json.loads((o / "results.json").read_text("utf-8")) for o in outs]
    assert results[0] == results[1]
    assert {"summary.md", "reliability.png", "environment.txt", "git_sha.txt"} <= {
        p.name for p in outs[0].iterdir()
    }
