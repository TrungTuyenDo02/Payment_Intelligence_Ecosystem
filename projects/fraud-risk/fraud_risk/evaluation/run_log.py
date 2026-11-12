"""Run log: run identity (AGENTS.md D6, ADR 0010), run folders and the test-once registry.

Two ids (ADR 0010):
- experiment_id (`compute_run_hash`): config, seed, dataset checksum and split bounds only. It
  names the result folder and is the test-once key, so it must not depend on library versions
  or the commit (upgrading a library would otherwise reopen the test set).
- execution_id (`execution_id`): one per run, adds start time, commit and environment. It is
  only for tracing a run (`executions/<execution_id>.json`) and is never used as a key.
"""

import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

PACKAGES = ["pandas", "numpy", "scikit-learn", "pyarrow", "pyyaml", "pydantic", "jsonschema"]


class AlreadyEvaluatedOnTestError(RuntimeError):
    """The test-once rule: this configuration hash was already evaluated on test."""


def canonical_config(config: dict[str, Any]) -> str:
    """Config as canonical JSON, without the `status` field (draft/frozen does not change a run)."""
    return json.dumps(
        {k: v for k, v in config.items() if k != "status"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def compute_run_hash(
    config: dict[str, Any], seed: int, manifest_checksum: str, split_boundaries: dict[str, Any]
) -> str:
    """SHA-256 of config (minus status), seed, dataset checksum and split bounds; no git SHA."""
    payload = json.dumps(
        {
            "config": canonical_config(config),
            "seed": seed,
            "manifest_checksum": manifest_checksum,
            "split_boundaries": split_boundaries,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def execution_id(experiment_id: str, started_at: datetime, commit: str, environment: str) -> str:
    """`exec-` + 12 hex of SHA-256(experiment id, UTC start, commit, environment text)."""
    payload = json.dumps(
        [experiment_id, started_at.astimezone(UTC).isoformat(), commit, environment],
        separators=(",", ":"),
    )
    return "exec-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def utc_now() -> datetime:
    """Current UTC time to the second (start of an execution)."""
    return datetime.now(UTC).replace(microsecond=0)


def write_execution(out: Path, experiment_id: str, started_at: datetime, repo_root: Path) -> str:
    """Write `out/executions/<execution_id>.json` and return the execution id.

    Records start/end, commit, environment and the SHA-256 of the files directly in `out`
    (sub-folders such as `test/` are not read). Result files themselves are not changed, so
    two executions of one experiment can be compared through these records.
    """
    environment, commit = environment_text(), git_sha(repo_root)
    eid = execution_id(experiment_id, started_at, commit, environment)
    files = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(out.iterdir())
        if p.is_file()
    }
    record = {
        "execution_id": eid,
        "experiment_id": experiment_id,
        "started_at": started_at.astimezone(UTC).isoformat(),
        "finished_at": utc_now().isoformat(),
        "commit": commit,
        "environment": environment.splitlines(),
        "files": files,
    }
    (out / "executions").mkdir(parents=True, exist_ok=True)
    write_json(out / "executions" / f"{eid}.json", record)
    return eid


def run_id_from_hash(run_hash: str) -> str:
    """Short, readable run id."""
    return f"run-{run_hash[:12]}"


def _clean(value: Any) -> Any:
    """Make values strict-JSON safe: NaN/inf -> None, numpy scalars -> Python."""
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_clean(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, str):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, data: Any) -> None:
    """Deterministic JSON (sorted keys, fixed indent, trailing newline)."""
    text = json.dumps(_clean(data), indent=2, sort_keys=True, allow_nan=False)
    path.write_text(text + "\n", encoding="utf-8")


def environment_text() -> str:
    """Python, platform and package versions."""
    lines = [f"python {sys.version.split()[0]}", f"platform {platform.platform()}"]
    for name in PACKAGES:
        try:
            lines.append(f"{name} {metadata.version(name)}")
        except metadata.PackageNotFoundError:
            lines.append(f"{name} not-installed")
    return "\n".join(lines) + "\n"


def git_sha(repo_root: Path) -> str:
    """Current commit, with `-dirty` if there are uncommitted changes; `unknown` outside git."""
    try:
        sha = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def write_run(
    run_dir: Path,
    *,
    config_text: str,
    metrics: dict[str, Any],
    split: dict[str, Any],
    thresholds: dict[str, Any],
    manifest_checksum: str,
    models: dict[str, Any],
    repo_root: Path,
) -> list[Path]:
    """Write every run-log file into `run_dir` and return their paths."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "config.yaml").write_text(config_text, encoding="utf-8")
    write_json(run_dir / "metrics.json", metrics)
    write_json(run_dir / "split.json", split)
    write_json(run_dir / "threshold.json", thresholds)
    write_json(run_dir / "models.json", models)
    (run_dir / "environment.txt").write_text(environment_text(), encoding="utf-8")
    (run_dir / "git_sha.txt").write_text(git_sha(repo_root) + "\n", encoding="utf-8")
    (run_dir / "manifest_checksum.txt").write_text(manifest_checksum + "\n", encoding="utf-8")
    return sorted(run_dir.iterdir())


def check_test_once(registry: Path, run_hash: str, force: bool) -> str | None:
    """Raise if `run_hash` is already registered (unless forced); return a warning when forced."""
    entries = json.loads(registry.read_text("utf-8")) if registry.is_file() else []
    if any(entry["hash"] == run_hash for entry in entries):
        if not force:
            raise AlreadyEvaluatedOnTestError(
                f"config hash {run_hash[:12]} was already evaluated on test "
                f"({registry}). Test-once rule: change the config (new hash) or pass --force; "
                "--force is recorded as a warning in metrics.json."
            )
        return (
            f"--force used: config hash {run_hash[:12]} had already been evaluated on test; "
            "these test numbers are not a first look and must be disclosed as such."
        )
    return None


def register_test_run(
    registry: Path, run_hash: str, run_id: str, forced: bool, execution_id: str | None = None
) -> None:
    """Append this test evaluation to the registry (older entries are never changed)."""
    entries = json.loads(registry.read_text("utf-8")) if registry.is_file() else []
    entry: dict[str, Any] = {
        "hash": run_hash,
        "run_id": run_id,
        "forced": forced,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if execution_id is not None:
        entry["execution_id"] = execution_id
    entries.append(entry)
    registry.parent.mkdir(parents=True, exist_ok=True)
    write_json(registry, entries)
