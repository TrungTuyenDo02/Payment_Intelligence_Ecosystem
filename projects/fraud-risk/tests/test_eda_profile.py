"""Tests for the EDA profiling script (T05b)."""

from pathlib import Path

import pandas as pd
import pytest
from fraud_risk.adapters.ieee_cis import load_ieee_cis
from fraud_risk.eda.profile import main, run_profile
from fraud_risk.evaluation.split import SplitError, random_split, time_split

DESCRIPTIVE = "descriptive_only"


def _run(ieee_dir: Path, out: Path, *, perturb_holdout: bool = False) -> dict[str, bytes]:
    data = load_ieee_cis(ieee_dir, use_identity=True)
    split = time_split(data.time)
    X, y = data.X.copy(), data.y.copy()
    if perturb_holdout:
        holdout = split.valid.append(split.test)
        X.loc[holdout, "TransactionAmt"] = X.loc[holdout, "TransactionAmt"] * 1000
        X.loc[holdout, "ProductCD"] = "Z"
        X.loc[holdout, "C1"] = None
        y.loc[holdout] = 1 - y.loc[holdout]
    run_profile(X, y, data.time, split, out)
    return {p.name: p.read_bytes() for p in sorted(out.glob("*.csv"))}


def test_six_steps_written(ieee_dir: Path, tmp_path: Path) -> None:
    files = _run(ieee_dir, tmp_path / "eda")
    for prefix in ["01_", "02_", "03_", "04_", "05_", "06_"]:
        assert any(name.startswith(prefix) for name in files), prefix
    assert (tmp_path / "eda" / "03_fraud_rate_by_week_train.png").is_file()
    assert (tmp_path / "eda" / "04_transaction_amt_raw_vs_log.png").is_file()
    profile = pd.read_csv(tmp_path / "eda" / "01_profile.csv").set_index("metric")["value"]
    assert profile["rows"] == pytest.approx(1200, abs=5)  # about 60% of 2000 rows (ties)


def test_decision_tables_use_train_only(ieee_dir: Path, tmp_path: Path) -> None:
    base = _run(ieee_dir, tmp_path / "a")
    changed = _run(ieee_dir, tmp_path / "b", perturb_holdout=True)
    decision_tables = [name for name in base if DESCRIPTIVE not in name]
    assert len(decision_tables) >= 10
    for name in decision_tables:
        assert base[name] == changed[name], f"{name} changed when only valid/test rows changed"
    descriptive = [name for name in base if DESCRIPTIVE in name]
    assert descriptive and any(base[n] != changed[n] for n in descriptive)


def test_leakage_candidates_flag_id_and_injected_label_copy(ieee_dir: Path, tmp_path: Path) -> None:
    data = load_ieee_cis(ieee_dir)
    X = data.X.assign(label_copy=data.y.to_numpy() * 7.0)
    run_profile(X, data.y, data.time, time_split(data.time), tmp_path)
    cand = pd.read_csv(tmp_path / "06_leakage_candidates.csv").set_index("column")["reasons"]
    assert "near_perfect_label_association" in cand["label_copy"]
    assert "encodes_time_or_order" in cand["TransactionDT"]
    assert "unique_per_row" in cand["(index) TransactionID"]


def test_missing_groups_and_identity_effect(ieee_dir: Path, tmp_path: Path) -> None:
    _run(ieee_dir, tmp_path)
    identity = pd.read_csv(tmp_path / "02_identity_effect.csv")
    assert set(identity["group"]) == {"with_identity", "without_identity"}
    groups = pd.read_csv(tmp_path / "02_missing_groups.csv")
    assert any("id_01" in cols and "DeviceType" in cols for cols in groups["columns"])


def test_random_split_rejected(ieee_dir: Path, tmp_path: Path) -> None:
    data = load_ieee_cis(ieee_dir)
    with pytest.raises(SplitError):
        run_profile(data.X, data.y, data.time, random_split(data.X.index), tmp_path)


def test_cli_dataset_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--data-dir", str(tmp_path), "--out-dir", str(tmp_path / "eda")]) == 2
    assert "dataset not found" in capsys.readouterr().err


def test_cli_with_config(ieee_dir: Path, tmp_path: Path) -> None:
    config = tmp_path / "c.yaml"
    config.write_text("split:\n  train_frac: 0.5\n  valid_frac: 0.25\n")
    args = [
        "--data-dir",
        str(ieee_dir),
        "--out-dir",
        str(tmp_path / "eda"),
        "--config",
        str(config),
    ]
    assert main(args) == 0
    profile = pd.read_csv(tmp_path / "eda" / "01_profile.csv").set_index("metric")["value"]
    assert profile["rows"] == pytest.approx(1000, abs=5)
