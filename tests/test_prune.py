import json
import uuid
from pathlib import Path

from claude_rescue import cmd_prune_acompact


class Args:
    def __init__(self, project_path, dry_run=False):
        self.project_path = str(project_path)
        self.dry_run = dry_run


def make_acompact_tree(base: Path) -> tuple[Path, Path, Path]:
    """Create session dir with subagents/agent-acompact-*.jsonl and a regular session."""
    session_id = str(uuid.uuid4())
    session_file = base / f"{session_id}.jsonl"
    session_file.write_text(json.dumps({"uuid": str(uuid.uuid4()), "type": "user"}) + "\n")

    subagents_dir = base / session_id / "subagents"
    subagents_dir.mkdir(parents=True)

    compact_file = subagents_dir / f"agent-acompact-{uuid.uuid4().hex[:16]}.jsonl"
    compact_file.write_text(json.dumps({"uuid": str(uuid.uuid4())}) + "\n")

    bak_file = compact_file.with_suffix(".jsonl.bak")
    bak_file.write_text("old backup\n")

    return session_file, compact_file, bak_file


def test_prune_deletes_acompact_files(tmp_path):
    session_file, compact_file, bak_file = make_acompact_tree(tmp_path)

    cmd_prune_acompact(Args(tmp_path))

    assert not compact_file.exists()
    assert not bak_file.exists()
    assert session_file.exists()


def test_prune_removes_empty_dirs(tmp_path):
    session_file, compact_file, bak_file = make_acompact_tree(tmp_path)
    subagents_dir = compact_file.parent
    session_subdir = subagents_dir.parent

    cmd_prune_acompact(Args(tmp_path))

    assert not subagents_dir.exists()
    assert not session_subdir.exists()


def test_prune_dry_run_deletes_nothing(tmp_path):
    _, compact_file, bak_file = make_acompact_tree(tmp_path)

    cmd_prune_acompact(Args(tmp_path, dry_run=True))

    assert compact_file.exists()
    assert bak_file.exists()


def test_prune_leaves_regular_sessions(tmp_path):
    session_file, _, _ = make_acompact_tree(tmp_path)
    cmd_prune_acompact(Args(tmp_path))
    assert session_file.exists()
