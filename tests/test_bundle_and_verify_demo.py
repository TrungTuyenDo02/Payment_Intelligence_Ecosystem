"""G07 / ADR 0010: small committable result bundles and `make verify-demo`."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle = load("bundle_results")
verify = load("verify_demo")


def run_folder(root: Path, name: str = "cal-abc") -> Path:
    out = root / "artifacts" / "experiments" / name
    (out / "executions").mkdir(parents=True)
    for file in ("config.yaml", "results.json", "summary.md", "environment.txt", "git_sha.txt"):
        (out / file).write_text(file, encoding="utf-8")
    (out / "executions" / "exec-1.json").write_text("{}", encoding="utf-8")
    (out / "scores.parquet").write_bytes(b"rows")  # per-row data: never bundled
    (out / "model.joblib").write_bytes(b"model")
    (out / "reliability.png").write_bytes(b"png")
    return out


def test_bundle_copies_only_small_summary_files(tmp_path: Path) -> None:
    src = run_folder(tmp_path)
    dest = bundle.bundle(src, tmp_path / "results")
    assert dest == tmp_path / "results" / "cal-abc"
    names = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert names == {"config.yaml", "results.json", "summary.md", "environment.txt",
                     "git_sha.txt", "executions/exec-1.json"}  # fmt: skip
    again = bundle.bundle(src, tmp_path / "results")  # re-bundling replaces, never mixes
    assert again == dest


def test_bundle_never_descends_into_test_and_needs_the_owner_flag_for_it(tmp_path: Path) -> None:
    src = tmp_path / "artifacts" / "runs" / "run-abc"
    (src / "test").mkdir(parents=True)
    (src / "metrics.json").write_text("{}", encoding="utf-8")
    (src / "test" / "metrics.json").write_text('{"test": 1}', encoding="utf-8")
    dest = bundle.bundle(src, tmp_path / "results")
    assert not (dest / "test").exists()
    with pytest.raises(bundle.BundleError, match="owner"):
        bundle.bundle(src / "test", tmp_path / "results")
    owner = bundle.bundle(src / "test", tmp_path / "results", owner_test=True)
    assert owner == tmp_path / "results" / "run-abc" / "test"


def test_bundle_refuses_empty_and_oversized_folders(tmp_path: Path) -> None:
    empty = tmp_path / "artifacts" / "experiments" / "nothing"
    empty.mkdir(parents=True)
    with pytest.raises(bundle.BundleError, match="no result files"):
        bundle.bundle(empty, tmp_path / "results")
    big = run_folder(tmp_path, "pol-big")
    (big / "results.json").write_bytes(b"x" * (bundle.MAX_BYTES + 1))
    with pytest.raises(bundle.BundleError, match="MB"):
        bundle.bundle(big, tmp_path / "results")
    assert not (tmp_path / "results" / "pol-big").exists()


def test_verify_demo_names_what_is_missing(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    problems = verify.missing(artifacts)
    assert len(problems) == 3 and "artifacts/runs" in problems[0]
    (artifacts / "runs" / "run-a").mkdir(parents=True)
    (artifacts / "runs" / "run-a" / "metrics.json").write_text("{}", encoding="utf-8")
    assert len(verify.missing(artifacts)) == 1  # only the Product 01 detector run is missing
    det = artifacts / "detections" / "det-a"
    det.mkdir(parents=True)
    (det / "evaluation.json").write_text(json.dumps({}), encoding="utf-8")
    assert verify.missing(artifacts) == []
    assert verify.main(["--artifacts-dir", str(artifacts)]) == 0
    assert verify.main(["--artifacts-dir", str(tmp_path / "none")]) == 1
