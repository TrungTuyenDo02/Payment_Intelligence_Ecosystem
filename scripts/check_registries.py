"""CI guard for the two test-once registries (ADR 0010).

Compares each registry with its version at a base git ref (the PR's target branch, or the
previous commit on a push) and fails when:

- an entry of the base is missing or changed (entries are matched by `hash`);
- a new entry has `"forced": true`;
- a new entry repeats a hash that is already registered (a second test evaluation);
- the file is not a JSON list of objects that each have a `hash`.

Standard library only. Usage: python scripts/check_registries.py --base origin/main
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REGISTRIES = ("artifacts/test_runs.json", "artifacts/detect_report_runs.json")


class RegistryFormatError(ValueError):
    """A registry is not a JSON list of objects with a `hash`."""


def parse(text: str, where: str) -> list[dict[str, Any]]:
    """Registry entries from JSON text; raise RegistryFormatError on a bad shape."""
    try:
        entries = json.loads(text)
    except json.JSONDecodeError as err:
        raise RegistryFormatError(f"{where}: not valid JSON ({err})") from err
    if not isinstance(entries, list) or not all(
        isinstance(e, dict) and isinstance(e.get("hash"), str) for e in entries
    ):
        raise RegistryFormatError(f"{where}: must be a list of objects that each have a 'hash'")
    return entries


def compare(base: list[dict[str, Any]], current: list[dict[str, Any]], name: str) -> list[str]:
    """Problems found when going from `base` to `current` (empty list: append-only, unforced)."""
    problems = []
    remaining = list(current)
    for entry in base:
        if entry in remaining:
            remaining.remove(entry)
            continue
        same_hash = [e for e in current if e["hash"] == entry["hash"]]
        what = "changed" if same_hash else "deleted"
        problems.append(f"{name}: entry {entry.get('run_id', entry['hash'][:12])} was {what}")
    seen = {e["hash"] for e in base}
    for entry in remaining:
        label = entry.get("run_id", entry["hash"][:12])
        if entry.get("forced") is True:
            problems.append(f'{name}: new entry {label} has "forced": true')
        if entry["hash"] in seen:
            problems.append(f"{name}: new entry {label} repeats an already registered hash")
        seen.add(entry["hash"])
    return problems


def base_text(ref: str, path: str, repo: Path) -> str | None:
    """The file at `ref`, or None when it does not exist there."""
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, text=True
    )
    if result.returncode != 0:
        if "exists on disk, but not in" in result.stderr or "does not exist in" in result.stderr:
            return None
        raise RuntimeError(f"git show {ref}:{path} failed: {result.stderr.strip()}")
    return result.stdout


def check(ref: str, repo: Path) -> list[str]:
    """All problems in both registries against `ref`."""
    problems = []
    for path in REGISTRIES:
        try:
            old = base_text(ref, path, repo)
            base = parse(old, f"{ref}:{path}") if old is not None else []
            file = repo / path
            if not file.is_file():
                if base:
                    problems.append(f"{path}: file was deleted")
                continue
            current = parse(file.read_text("utf-8"), path)
        except RegistryFormatError as err:
            problems.append(str(err))
            continue
        problems += compare(base, current, path)
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="git ref to compare with")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    problems = check(args.base, args.repo)
    for line in problems:
        print(f"error: {line}", file=sys.stderr)
    if not problems:
        print(f"registries OK against {args.base}: append-only, no forced entries")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
