"""The commit-msg hook drops AI-tool attribution lines and keeps everything else."""

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".githooks" / "commit-msg"


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")
def test_hook_removes_attribution_only(tmp_path: Path) -> None:
    msg = tmp_path / "COMMIT_EDITMSG"
    msg.write_text(
        "Add dashboard\n\nBody line mentioning the agent.\n"
        "Co-Authored-By: Alice <alice@example.com>\n\n"
        "Co-Authored-By: Claude Opus <noreply@anthropic.com>\n"
        "Claude-Session: https://claude.ai/code/session_x\n"
        "🤖 Generated with [Claude Code](https://claude.com/claude-code)\n\n",
        encoding="utf-8",
    )
    subprocess.run(["sh", str(HOOK), str(msg)], check=True)
    assert msg.read_text("utf-8") == (
        "Add dashboard\n\nBody line mentioning the agent.\n"
        "Co-Authored-By: Alice <alice@example.com>\n"
    )


def test_hook_is_executable() -> None:
    assert HOOK.stat().st_mode & 0o111
