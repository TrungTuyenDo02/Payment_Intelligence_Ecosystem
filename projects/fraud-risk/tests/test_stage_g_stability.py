"""Stage G / G05: weekly and group stability on development data; PSI checked by hand."""

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.evaluation.split import time_split
from fraud_risk.experiments import decision_data as dd
from fraud_risk.experiments import stability as stab
from fraud_risk.scripts.config import StabilityConfig

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


@pytest.fixture(scope="module")
def data(ieee_dir_module: Path) -> Any:
    return load_ieee_cis(ieee_dir_module)


@pytest.fixture(scope="module")
def raw(stage_g_raw: Any) -> Any:
    return lambda time: stage_g_raw(time, "stability.yaml")


@pytest.fixture(scope="module")
def cfg(data: Any, raw: Any) -> StabilityConfig:
    return StabilityConfig.model_validate(raw(data.time))


@pytest.fixture(scope="module")
def result(data: Any, cfg: StabilityConfig) -> dict[str, Any]:
    return stab.run_stability(dd.prepare(data.X, data.y, data.time, cfg), cfg)


def test_real_config_is_draft() -> None:
    raw = yaml.safe_load((CONFIGS / "stability.yaml").read_text("utf-8"))
    parsed = StabilityConfig.model_validate(raw)
    assert parsed.status == "draft" and parsed.stage == "exploratory"
    assert parsed.stability.psi_columns == ["TransactionAmt", "C1", "C13", "hour_of_day"]
    assert parsed.stability.groups == ["ProductCD", "card6"]


def test_psi_matches_hand_computation() -> None:
    reference = pd.Series(np.arange(100, dtype=float))  # 10 equal deciles
    current = pd.Series(np.r_[np.zeros(30), np.arange(30, 100, dtype=float)])
    edges = stab.quantile_edges(reference, 10)
    got = stab.psi(reference, current, edges)
    # Train deciles of 0..99 hold 10 values each; current has 30 zeros, nothing in 10..29.
    ref_share = np.full(10, 0.1)
    cur_counts = np.histogram(np.clip(current, 0, 99), bins=np.arange(0, 101, 10))[0]
    cur_share = cur_counts / cur_counts.sum()
    expected = sum((c - r) * math.log(c / r) for c, r in zip(cur_share, ref_share, strict=True)
                   if c > 0)  # fmt: skip
    expected += sum((stab.EPS - r) * math.log(stab.EPS / r)
                    for c, r in zip(cur_share, ref_share, strict=True) if c == 0)  # fmt: skip
    assert got == pytest.approx(expected)


def test_psi_is_zero_for_the_same_distribution_and_counts_missing() -> None:
    rng = np.random.default_rng(0)
    ref = pd.Series(rng.normal(size=5000))
    edges = stab.quantile_edges(ref, 10)
    assert stab.psi(ref, ref, edges) == pytest.approx(0.0, abs=1e-12)
    with_missing = ref.copy()
    with_missing.iloc[:1000] = np.nan
    assert stab.psi(ref, with_missing, edges) > 0.1  # missing values form their own bin


def test_weeks_cover_development_data_only(data: Any, result: dict[str, Any]) -> None:
    split = time_split(data.time, 0.6, 0.2)
    weekly = result["weekly"]
    assert sum(w["rows"] for w in weekly if w["part"] == "train") == len(split.train)
    assert sum(w["rows"] for w in weekly if w["part"] == "valid") == len(split.valid)
    assert all(w["part"] == "train" or not w["in_sample"] for w in weekly)


def test_small_groups_are_flagged(cfg: StabilityConfig, result: dict[str, Any]) -> None:
    for row in result["groups"]:
        assert row["small_sample"] == (row["frauds"] < cfg.stability.min_frauds)


def test_test_rows_change_nothing(data: Any, cfg: StabilityConfig, result: dict) -> None:
    split = time_split(data.time, 0.6, 0.2)
    y2, X2 = data.y.copy(), data.X.copy()
    y2.loc[split.test] = 1 - y2.loc[split.test]
    X2.loc[split.test, ["TransactionAmt", "C1", "C13"]] = 1e6
    X2.loc[split.test, "ProductCD"] = "Z"
    other = stab.run_stability(dd.prepare(X2, y2, data.time, cfg), cfg)
    assert other == result


def test_permuted_labels_fall_to_chance(result: dict[str, Any]) -> None:
    check = result["self_checks"]
    assert abs(check["permuted_valid_pr_auc"] - check["valid_prevalence"]) < 0.05


def test_runner_is_reproducible(ieee_dir_module: Path, data: Any, tmp_path: Path, raw: Any) -> None:
    config = tmp_path / "stability.yaml"
    config.write_text(yaml.safe_dump(raw(data.time)), encoding="utf-8")
    manifest = ieee_dir_module.parent / "manifests" / "ieee-cis.yaml"
    outs = [
        stab.run(
            config,
            data_dir=ieee_dir_module,
            manifest_path=manifest,
            artifacts_dir=tmp_path / f"a{i}",
        )  # fmt: skip
        for i in range(2)
    ]
    assert outs[0].name == outs[1].name and outs[0].name.startswith("stab-")
    texts = [json.loads((o / "results.json").read_text("utf-8")) for o in outs]
    assert texts[0] == texts[1]
    assert {"summary.md", "stability.png"} <= {p.name for p in outs[0].iterdir()}
