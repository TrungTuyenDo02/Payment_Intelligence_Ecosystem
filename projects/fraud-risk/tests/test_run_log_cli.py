"""Tests for the run log, run identity (D6), frozen config (D5) and test-once rule (T09)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml
from fraud_risk.evaluation.run_log import compute_run_hash
from fraud_risk.scripts.run_baseline import main

BASE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml"
Workspace = tuple[Callable[..., Path], Callable[..., int], Path]
RUN_FILES = {
    "config.yaml",
    "metrics.json",
    "split.json",
    "threshold.json",
    "models.json",
    "environment.txt",
    "git_sha.txt",
    "manifest_checksum.txt",
}


@pytest.fixture
def workspace(ieee_dir: Path, tmp_path: Path) -> Workspace:
    def make_config(**overrides: object) -> Path:
        cfg = yaml.safe_load(BASE_CONFIG.read_text())
        cfg["metrics"]["bootstrap_resamples"] = 20
        cfg.update(overrides)
        path = tmp_path / f"config_{len(list(tmp_path.glob('config_*')))}.yaml"
        path.write_text(yaml.safe_dump(cfg, sort_keys=False))
        return path

    def cli(config: Path, *extra: str, artifacts: Path | None = None) -> int:
        args = ["--config", str(config), "--data-dir", str(ieee_dir)]
        args += ["--manifest", str(ieee_dir.parent / "manifests" / "ieee-cis.yaml")]
        args += ["--artifacts-dir", str(artifacts or tmp_path / "artifacts"), *extra]
        return main(args)

    return make_config, cli, tmp_path / "artifacts"


def _only_run(artifacts: Path) -> Path:
    runs = list((artifacts / "runs").iterdir())
    assert len(runs) == 1
    return runs[0]


def test_baseline_creates_full_run_folder(workspace: Workspace) -> None:
    make_config, cli, artifacts = workspace
    assert cli(make_config()) == 0
    run_dir = _only_run(artifacts)
    assert {p.name for p in run_dir.iterdir()} >= RUN_FILES
    metrics = json.loads((run_dir / "metrics.json").read_text())
    assert metrics["stage"] == "validation"
    for model in ("rule_based", "logistic"):
        assert set(metrics["models"][model]) == {"train", "valid"}  # never test
        assert 0 <= metrics["models"][model]["valid"]["pr_auc"] <= 1
    threshold = json.loads((run_dir / "threshold.json").read_text())
    assert threshold["logistic"]["chosen_on"] == "valid"
    split = json.loads((run_dir / "split.json").read_text())
    assert split["kind"] == "time" and "boundaries" in split
    rules = json.loads((run_dir / "models.json").read_text())["rule_based"]["rules"]
    assert all("description" in r for r in rules)
    assert not (artifacts / "test_runs.json").exists()


def test_reproducible_metrics(workspace: Workspace, tmp_path: Path) -> None:
    make_config, cli, _ = workspace
    config = make_config()
    assert cli(config, artifacts=tmp_path / "a") == 0
    assert cli(config, artifacts=tmp_path / "b") == 0
    a, b = _only_run(tmp_path / "a"), _only_run(tmp_path / "b")
    assert a.name == b.name
    assert (a / "metrics.json").read_bytes() == (b / "metrics.json").read_bytes()


def test_run_id_rules_d6() -> None:
    cfg = yaml.safe_load(BASE_CONFIG.read_text())
    bounds = {"train": {"min_time": 1, "max_time": 5}}
    base = compute_run_hash(cfg, 42, "abc", bounds)
    assert compute_run_hash({**cfg, "status": "frozen"}, 42, "abc", bounds) == base
    assert compute_run_hash(cfg, 43, "abc", bounds) != base
    assert compute_run_hash(cfg, 42, "abd", bounds) != base
    assert compute_run_hash(cfg, 42, "abc", {"train": {"min_time": 1, "max_time": 6}}) != base
    assert compute_run_hash({**cfg, "seed": 1}, 42, "abc", bounds) != base


def test_final_requires_frozen(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    make_config, cli, artifacts = workspace
    assert cli(make_config(status="draft"), "--stage", "final") == 2
    assert "frozen" in capsys.readouterr().err
    assert not (artifacts / "runs").exists()


def test_test_once_rule(workspace: Workspace, capsys: pytest.CaptureFixture[str]) -> None:
    make_config, cli, artifacts = workspace
    frozen = make_config(status="frozen")  # test fixture config, not the real one
    assert cli(frozen, "--stage", "final") == 0
    run_dir = _only_run(artifacts) / "test"
    first = json.loads((run_dir / "metrics.json").read_text())
    assert set(first["models"]["logistic"]) == {"train", "valid", "test"}
    assert first["warnings"] == []

    assert cli(frozen, "--stage", "final") == 2
    assert "already evaluated on test" in capsys.readouterr().err

    assert cli(frozen, "--stage", "final", "--force") == 0
    forced = json.loads((run_dir / "metrics.json").read_text())
    assert forced["warnings"] and "--force" in forced["warnings"][0]
    registry = json.loads((artifacts / "test_runs.json").read_text())
    assert [entry["forced"] for entry in registry] == [False, True]


def test_new_config_gets_new_test_slot(workspace: Workspace) -> None:
    make_config, cli, artifacts = workspace
    assert cli(make_config(status="frozen"), "--stage", "final") == 0
    assert cli(make_config(status="frozen", seed=7), "--stage", "final") == 0
    assert len(json.loads((artifacts / "test_runs.json").read_text())) == 2


def test_dataset_not_found_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--config", str(BASE_CONFIG), "--data-dir", str(tmp_path / "nothing")])
    assert code == 2
    assert "dataset not found" in capsys.readouterr().err


def test_missing_manifest_message(
    workspace: Workspace, ieee_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_config, _, _ = workspace
    (ieee_dir.parent / "manifests" / "ieee-cis.yaml").unlink()
    args = ["--config", str(make_config()), "--data-dir", str(ieee_dir)]
    args += ["--manifest", str(ieee_dir.parent / "manifests" / "ieee-cis.yaml")]
    assert main(args) == 2
    assert "Create the manifest" in capsys.readouterr().err


def test_changed_data_detected(
    workspace: Workspace, ieee_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_config, cli, _ = workspace
    path = ieee_dir / "train_transaction.csv"
    path.write_text(path.read_text().replace("W", "R", 1))
    assert cli(make_config()) == 2
    assert "changed since the manifest" in capsys.readouterr().err


def test_invalid_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("status: approved\nseed: 1\n")
    assert main(["--config", str(bad)]) == 2
    assert "invalid config" in capsys.readouterr().err
