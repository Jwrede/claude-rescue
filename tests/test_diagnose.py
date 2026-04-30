import json
from pathlib import Path

from claude_rescue import diagnose_file


def test_healthy(healthy_session):
    count, roots, broken, title = diagnose_file(healthy_session)
    assert count == 3
    assert roots == 1
    assert broken == 0
    assert title == "hello world"


def test_fragmented(fragmented_session):
    count, roots, broken, title = diagnose_file(fragmented_session)
    assert count == 5
    assert roots == 2
    assert broken == 0
    assert title == "chain one"


def test_corrupted(corrupted_session):
    count, roots, broken, title = diagnose_file(corrupted_session)
    assert count == 2
    assert broken == 1
    assert title == "broken"


def test_empty(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    count, roots, broken, title = diagnose_file(path)
    assert count == 0
    assert roots == 0
    assert broken == 0
    assert title == ""


def test_meta_only(tmp_path):
    path = tmp_path / "meta.jsonl"
    path.write_text(json.dumps({"type": "permission-mode", "permissionMode": "default"}) + "\n")
    count, roots, broken, title = diagnose_file(path)
    assert count == 1
    assert roots == 0
