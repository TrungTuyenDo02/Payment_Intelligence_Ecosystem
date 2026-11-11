"""G07 / ADR 0010: the CI guard keeps both test-once registries append-only and unforced."""

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_registries.py"
spec = importlib.util.spec_from_file_location("check_registries", SCRIPT)
assert spec and spec.loader
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)

OLD = [
    {"hash": "a" * 64, "run_id": "run-aaaaaaaaaaaa", "forced": False},
    {"hash": "b" * 64, "run_id": "run-bbbbbbbbbbbb", "forced": False, "note": "other machine"},
]
NEW = {"hash": "c" * 64, "run_id": "run-cccccccccccc", "forced": False}


def test_appending_an_unforced_entry_is_fine() -> None:
    assert cr.compare(OLD, [*OLD, NEW], "r") == []
    assert cr.compare([], [NEW], "r") == []


def test_deleted_changed_forced_and_repeated_entries_are_errors() -> None:
    assert "was deleted" in cr.compare(OLD, OLD[1:], "r")[0]
    changed = [{**OLD[0], "forced": True}, OLD[1]]
    assert "was changed" in cr.compare(OLD, changed, "r")[0]
    assert "forced" in cr.compare(OLD, [*OLD, {**NEW, "forced": True}], "r")[0]
    repeated = cr.compare(OLD, [*OLD, {**OLD[0], "recorded_at": "later"}], "r")
    assert any("repeats" in p for p in repeated)


def test_key_order_and_formatting_do_not_matter() -> None:
    reordered = [dict(reversed(list(e.items()))) for e in OLD]
    assert cr.compare(OLD, reordered, "r") == []


def test_bad_shapes_are_rejected() -> None:
    for text in ("{not json", '{"hash": "x"}', '[{"run_id": "no hash"}]'):
        with pytest.raises(cr.RegistryFormatError):
            cr.parse(text, "r")


def test_the_committed_registries_parse_and_have_no_forced_entries() -> None:
    for path in cr.REGISTRIES:
        entries = cr.parse((ROOT / path).read_text("utf-8"), path)
        assert entries and not any(e.get("forced") for e in entries)
        assert len({e["hash"] for e in entries}) == len(entries)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_check_against_a_git_ref(tmp_path: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    def write(entries: list[dict[str, Any]]) -> None:
        for path in cr.REGISTRIES:
            (tmp_path / path).write_text(json.dumps(entries), encoding="utf-8")

    git("init", "-q")
    git("config", "user.email", "ci@example.invalid")
    git("config", "user.name", "ci")
    (tmp_path / "artifacts").mkdir()
    write(OLD)
    git("add", ".")
    git("commit", "-q", "--no-verify", "-m", "base")
    write([*OLD, NEW])
    assert cr.check("HEAD", tmp_path) == []
    assert cr.main(["--base", "HEAD", "--repo", str(tmp_path)]) == 0
    write(OLD[:1])
    assert len(cr.check("HEAD", tmp_path)) == 2  # one deletion in each registry
    assert cr.main(["--base", "HEAD", "--repo", str(tmp_path)]) == 1
    (tmp_path / cr.REGISTRIES[0]).unlink()
    assert any("file was deleted" in p for p in cr.check("HEAD", tmp_path))
    with pytest.raises(RuntimeError):
        cr.check("no-such-ref", tmp_path)
