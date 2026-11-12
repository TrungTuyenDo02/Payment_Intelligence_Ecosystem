"""G07 / ADR 0010: experiment_id keeps the published formula; execution_id tracks each run."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from fraud_risk.evaluation import run_log

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
# Published split of IEEE-CIS (artifacts/runs/run-f8807cb6f780/split.json) and manifest checksum.
BOUNDS = {
    "test": {"max_time": 15811131, "min_time": 12192900},
    "train": {"max_time": 8745772, "min_time": 86400},
    "train_frac": 0.6,
    "valid": {"max_time": 12192842, "min_time": 8745798},
    "valid_frac": 0.2,
}
CHECKSUM = "f7320fa9ffd559204ce2eb3167393e7b1a276874a32c397d7b011f48e34313ba"
STARTED = datetime(2026, 11, 11, 8, 0, tzinfo=UTC)


def test_experiment_id_formula_is_unchanged_for_published_runs() -> None:
    registry = json.loads(Path(CONFIGS.parents[2] / "artifacts/test_runs.json").read_text("utf-8"))
    registered = {e["hash"] for e in registry}
    for name, expected in (
        ("gbm.yaml", "f8807cb6f7806b3bfb0105f0997a2af41ad9e17f46a0c8a774deec75624feddf"),
        ("baseline.yaml", "d6faa46990087eddb0a4078ef829933085e651a717c4af8d3ccc67475f6dc1cb"),
    ):
        raw = yaml.safe_load((CONFIGS / name).read_text("utf-8"))
        got = run_log.compute_run_hash(raw, raw["seed"], CHECKSUM, BOUNDS)
        assert got == expected and got in registered


def test_execution_id_changes_per_run_but_never_the_experiment_id() -> None:
    a = run_log.execution_id("run-x", STARTED, "abc", "python 3.11\n")
    assert a.startswith("exec-") and len(a) == len("exec-") + 12
    assert a == run_log.execution_id("run-x", STARTED, "abc", "python 3.11\n")
    later = STARTED.replace(minute=1)
    others = {
        run_log.execution_id("run-x", later, "abc", "python 3.11\n"),
        run_log.execution_id("run-x", STARTED, "abd", "python 3.11\n"),
        run_log.execution_id("run-x", STARTED, "abc", "python 3.13\n"),
        run_log.execution_id("run-y", STARTED, "abc", "python 3.11\n"),
    }
    assert a not in others and len(others) == 4


def test_write_execution_records_top_level_files_only(tmp_path: Path) -> None:
    (tmp_path / "metrics.json").write_text('{"a": 1}\n', encoding="utf-8")
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "metrics.json").write_text("{}", encoding="utf-8")
    before = (tmp_path / "metrics.json").read_bytes()
    eid = run_log.write_execution(tmp_path, "run-x", STARTED, tmp_path)
    record = json.loads((tmp_path / "executions" / f"{eid}.json").read_text("utf-8"))
    assert record["execution_id"] == eid and record["experiment_id"] == "run-x"
    assert record["started_at"] == "2026-11-11T08:00:00+00:00"
    assert record["files"] == {"metrics.json": hashlib.sha256(before).hexdigest()}
    assert record["commit"] == "unknown"  # tmp_path is not a git checkout
    assert any(line.startswith("python ") for line in record["environment"])
    assert (tmp_path / "metrics.json").read_bytes() == before  # results stay byte-identical
    second = run_log.write_execution(tmp_path, "run-x", STARTED.replace(second=1), tmp_path)
    assert second != eid and len(list((tmp_path / "executions").iterdir())) == 2


def test_register_test_run_records_the_execution_id(tmp_path: Path) -> None:
    registry = tmp_path / "test_runs.json"
    run_log.register_test_run(registry, "h1", "run-h1", forced=False)
    run_log.register_test_run(registry, "h2", "run-h2", forced=False, execution_id="exec-1")
    entries = json.loads(registry.read_text("utf-8"))
    assert "execution_id" not in entries[0] and entries[1]["execution_id"] == "exec-1"
