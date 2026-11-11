"""Stage G / G04: policies chosen on V2 only, evaluated on V3; costs checked by hand."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.evaluation.split import time_split
from fraud_risk.experiments import decision_data as dd
from fraud_risk.experiments import policy as pol
from fraud_risk.scripts.config import PolicyConfig

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
COST = pol.Cost(loss_rate=0.75, c_review=5.0, c_friction=1.0)


@pytest.fixture(scope="module")
def data(ieee_dir_module: Path) -> Any:
    return load_ieee_cis(ieee_dir_module)


@pytest.fixture(scope="module")
def _raw(stage_g_raw: Any) -> Any:
    def build(time: pd.Series) -> dict[str, Any]:
        raw = stage_g_raw(time, "policy.yaml")
        raw["policy"]["bootstrap"]["resamples"] = 50
        return raw

    return build


@pytest.fixture(scope="module")
def cfg(data: Any, _raw: Any) -> PolicyConfig:
    return PolicyConfig.model_validate(_raw(data.time))


@pytest.fixture(scope="module")
def dev(data: Any, cfg: PolicyConfig) -> dd.DevData:
    return dd.prepare(data.X, data.y, data.time, cfg)


@pytest.fixture(scope="module")
def result(dev: dd.DevData, cfg: PolicyConfig) -> dict[str, Any]:
    return pol.run_policy(dev, cfg)


def test_real_config_is_draft_with_the_approved_grid() -> None:
    parsed = PolicyConfig.model_validate(
        yaml.safe_load((CONFIGS / "policy.yaml").read_text("utf-8"))
    )
    assert parsed.status == "draft" and parsed.stage == "exploratory"
    grid = parsed.policy.cost
    assert (grid.loss_rate, grid.c_review, grid.c_friction) == (
        [0.5, 0.75, 1.0], [1, 5, 25], [0, 1, 10]
    )  # fmt: skip
    assert parsed.policy.budgets_pct == [0.5, 1, 2, 5]
    assert parsed.models.logistic is None


def test_cost_matches_pure_python() -> None:
    rng = np.random.default_rng(2)
    y = (rng.random(1000) < 0.05).astype(int)
    amount = np.round(rng.lognormal(4, 1, 1000), 2)
    alert = rng.random(1000) < 0.1
    expected = 0.0
    for yi, ai, flag in zip(y, amount, alert, strict=True):
        if flag:
            expected += COST.c_review + (COST.c_friction if yi == 0 else 0.0)
        elif yi == 1:
            expected += COST.loss_rate * ai
    got = pol.outcome(y, amount, alert, COST)
    assert got["cost"] == pytest.approx(expected)
    assert got["alerts"] == int(alert.sum()) and got["tp"] == int((alert & (y == 1)).sum())


def test_cost_threshold_is_the_best_cut_on_the_select_rows() -> None:
    rng = np.random.default_rng(3)
    y = (rng.random(500) < 0.1).astype(int)
    scores = rng.random(500) * 0.5 + 0.5 * y * rng.random(500)
    amount = rng.lognormal(4, 1, 500)
    t = pol.cost_threshold(y, scores, amount, COST)
    best = pol.outcome(y, amount, scores >= t, COST)["cost"]
    for cut in np.unique(scores):  # brute force over every possible cut
        assert pol.outcome(y, amount, scores >= cut, COST)["cost"] >= best - 1e-9
    assert pol.outcome(y, amount, np.zeros(500, bool), COST)["cost"] >= best - 1e-9


def test_selection_refuses_the_evaluate_block(dev: dd.DevData, cfg: PolicyConfig) -> None:
    """Sabotage: choosing thresholds on V3 must fail loudly."""
    v3 = dd.blocks(dev)["V3"]
    with pytest.raises(dd.BlockRoleError):
        pol.select_thresholds(dev, v3, [COST], cfg.policy.fpr_target)


def test_top_n_per_day_ignores_later_days(dev: dd.DevData) -> None:
    frame = dev.frame.loc[dd.blocks(dev)["V3"].index]
    first = pol.top_n_per_day(frame["day"], frame["score_gbm"], 5.0)
    later = frame["day"] > frame["day"].min()
    changed = frame["score_gbm"].where(~later, 1 - frame["score_gbm"])
    again = pol.top_n_per_day(frame["day"], changed, 5.0)
    assert (first[~later.to_numpy()] == again[~later.to_numpy()]).all()
    per_day = pd.Series(first).groupby(frame["day"].to_numpy()).agg(["sum", "size"])
    assert (per_day["sum"] == np.ceil(per_day["size"] * 0.05)).all()


def test_v3_labels_change_no_choice(dev: dd.DevData, cfg: PolicyConfig, result: dict) -> None:
    frame = dev.frame.copy()
    v3 = frame["block"] == "V3"
    frame.loc[v3, "y"] = 1 - frame.loc[v3, "y"]
    flipped = pol.run_policy(dd.DevData(**{**dev.__dict__, "frame": frame}), cfg)
    assert flipped["selected"] == result["selected"]


def test_test_rows_change_nothing(data: Any, cfg: PolicyConfig, result: dict) -> None:
    split = time_split(data.time, 0.6, 0.2)
    y2, X2 = data.y.copy(), data.X.copy()
    y2.loc[split.test] = 1 - y2.loc[split.test]
    X2.loc[split.test, "TransactionAmt"] = 9e5
    assert pol.run_policy(dd.prepare(X2, y2, data.time, cfg), cfg) == result


def test_every_policy_and_cost_is_reported(cfg: PolicyConfig, result: dict) -> None:
    grid = cfg.policy.cost
    n_costs = len(grid.loss_rate) * len(grid.c_review) * len(grid.c_friction)
    n_policies = 5 + len(cfg.policy.budgets_pct)  # none, max_f1, cost_v2, 2 rules + budgets
    assert len(result["v3"]) == n_costs * n_policies
    row = result["v3"][0]
    assert {"cost", "cost_ci_day", "cost_ci_card1", "delta_vs_max_f1_ci_day"} <= set(row)
    assert result["self_checks"]["calibrated_v2_threshold_same_alerts"] is True


def test_permuted_labels_catch_only_the_alert_share(result: dict) -> None:
    check = result["self_checks"]["permuted_v3"]
    assert abs(check["recall"] - check["alert_rate"]) < 0.1


def test_runner_is_reproducible(
    ieee_dir_module: Path, data: Any, tmp_path: Path, _raw: Any
) -> None:
    config = tmp_path / "policy.yaml"
    config.write_text(yaml.safe_dump(_raw(data.time)), encoding="utf-8")
    manifest = ieee_dir_module.parent / "manifests" / "ieee-cis.yaml"
    outs = [
        pol.run(
            config,
            data_dir=ieee_dir_module,
            manifest_path=manifest,
            artifacts_dir=tmp_path / f"a{i}",
        )  # fmt: skip
        for i in range(2)
    ]
    assert outs[0].name == outs[1].name and outs[0].name.startswith("pol-")
    texts = [json.loads((o / "results.json").read_text("utf-8")) for o in outs]
    assert texts[0] == texts[1]
    assert (outs[0] / "summary.md").is_file()
