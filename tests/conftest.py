"""Shared fixtures for claude-rescue tests."""
import json
import uuid
from pathlib import Path

import pytest


def make_entry(uid: str, parent: str | None = None, extra: dict | None = None) -> dict:
    e = {"uuid": uid, "parentUuid": parent, "type": "user", "sessionId": "test"}
    if extra:
        e.update(extra)
    return e


def write_jsonl(path: Path, entries: list[dict]) -> None:
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir()
    return d


@pytest.fixture
def healthy_session(project_dir: Path) -> Path:
    """Single chain: root -> child -> grandchild."""
    r, c, g = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    path = project_dir / f"{uuid.uuid4()}.jsonl"
    write_jsonl(path, [
        make_entry(r, None, {"lastPrompt": "hello world"}),
        make_entry(c, r),
        make_entry(g, c),
    ])
    return path


@pytest.fixture
def fragmented_session(project_dir: Path) -> Path:
    """Two independent chains in one file."""
    r1, c1 = str(uuid.uuid4()), str(uuid.uuid4())
    r2, c2 = str(uuid.uuid4()), str(uuid.uuid4())
    path = project_dir / f"{uuid.uuid4()}.jsonl"
    write_jsonl(path, [
        make_entry(r1, None, {"lastPrompt": "chain one"}),
        make_entry(c1, r1),
        make_entry(r2, None),    # second root — fragmented
        make_entry(c2, r2),
        make_entry(str(uuid.uuid4()), c2),  # chain 2 has more entries → should win
    ])
    return path


@pytest.fixture
def corrupted_session(project_dir: Path) -> Path:
    """Entry whose parentUuid doesn't exist in the file."""
    r, c = str(uuid.uuid4()), str(uuid.uuid4())
    path = project_dir / f"{uuid.uuid4()}.jsonl"
    write_jsonl(path, [
        make_entry(r, None, {"lastPrompt": "broken"}),
        make_entry(c, "nonexistent-parent-uuid"),
    ])
    return path
