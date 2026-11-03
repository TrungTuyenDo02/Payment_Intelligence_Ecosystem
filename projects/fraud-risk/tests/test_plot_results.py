"""Tests for the result report (`make report`): charts and summary from a run folder."""

from pathlib import Path

import pytest
import yaml
from fraud_risk.scripts.plot_results import ReportError, build_report, latest_run_dir, main
from fraud_risk.scripts.run_baseline import main as run_baseline

BASE_CONFIG = Path(__file__).resolve().parents[1] / "configs" / "baseline.yaml"


@pytest.fixture
def run_dir(ieee_dir: Path, tmp_path: Path) -> Path:
    cfg = yaml.safe_load(BASE_CONFIG.read_text())
    cfg["metrics"]["bootstrap_resamples"] = 20
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg, sort_keys=False))
    args = ["--config", str(config), "--data-dir", str(ieee_dir)]
    args += ["--manifest", str(ieee_dir.parent / "manifests" / "ieee-cis.yaml")]
    args += ["--artifacts-dir", str(tmp_path / "artifacts")]
    assert run_baseline(args) == 0
    return latest_run_dir(tmp_path / "artifacts")


def test_report_writes_charts_and_summary(run_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "report"
    assert main(["--run-dir", str(run_dir), "--out", str(out)]) == 0
    for name in ("split.png", "pr_auc.png", "recall_targets.png"):
        assert (out / name).stat().st_size > 0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert run_dir.name in summary
    assert "Validation" in summary and "Test" not in summary  # validation run never shows test
    assert summary.count("\n| ") == 2 + 2  # header, separator, one row per model


def test_report_without_runs_fails_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--artifacts-dir", str(tmp_path), "--out", str(tmp_path / "out")]) == 1
    assert "run `make baseline` first" in capsys.readouterr().err


def test_incomplete_run_folder_fails_clearly(tmp_path: Path) -> None:
    (tmp_path / "metrics.json").write_text("{}")
    with pytest.raises(ReportError, match="split.json"):
        build_report(tmp_path, tmp_path / "out")
