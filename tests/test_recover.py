import json
import uuid
from pathlib import Path

from claude_rescue import _recover_file, _get_last_prompt


def test_healthy_no_op(healthy_session, project_dir):
    root_count, written, meta, out_path, new_id, already = _recover_file(
        healthy_session, project_dir
    )
    assert root_count == 1
    assert out_path is None
    assert new_id is None
    assert not already


def test_fragmented_recovers_best_chain(fragmented_session, project_dir):
    root_count, written, meta, out_path, new_id, already = _recover_file(
        fragmented_session, project_dir
    )
    assert root_count == 2
    assert out_path is not None
    assert out_path.exists()
    # Best chain is the longer one (3 entries)
    assert written == 3


def test_recovered_file_is_valid_jsonl(fragmented_session, project_dir):
    _, _, _, out_path, _, _ = _recover_file(fragmented_session, project_dir)
    lines = [json.loads(l) for l in out_path.read_text().splitlines() if l.strip()]
    uuids = [e["uuid"] for e in lines if "uuid" in e]
    # All parentUuids should resolve within the file
    uuid_set = set(uuids)
    for e in lines:
        parent = e.get("parentUuid")
        if parent:
            assert parent in uuid_set


def test_duplicate_detection(fragmented_session, project_dir):
    _, _, _, out_path1, new_id1, already1 = _recover_file(fragmented_session, project_dir)
    assert not already1

    _, _, _, out_path2, new_id2, already2 = _recover_file(fragmented_session, project_dir)
    assert already2
    assert new_id2 == new_id1
    assert out_path2 == out_path1


def test_duplicate_invalidated_when_file_deleted(fragmented_session, project_dir):
    _, _, _, out_path, new_id, _ = _recover_file(fragmented_session, project_dir)
    out_path.unlink()

    _, _, _, out_path2, new_id2, already2 = _recover_file(fragmented_session, project_dir)
    assert not already2
    assert new_id2 != new_id


def test_get_last_prompt(fragmented_session):
    assert _get_last_prompt(fragmented_session) == "chain one"


def test_get_last_prompt_returns_last_occurrence(tmp_path):
    """`lastPrompt` is updated per-entry; we must return the final one to match
    what `claude resume` displays."""
    path = tmp_path / "session.jsonl"
    entries = [
        {"uuid": "a", "parentUuid": None, "lastPrompt": "first prompt"},
        {"uuid": "b", "parentUuid": "a", "lastPrompt": "middle prompt"},
        {"uuid": "c", "parentUuid": "b", "lastPrompt": "latest prompt"},
    ]
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    assert _get_last_prompt(path) == "latest prompt"


def test_in_place_recovery(fragmented_session, project_dir):
    original_stem = fragmented_session.stem
    root_count, written, meta, out_path, new_id, already = _recover_file(
        fragmented_session, project_dir, in_place=True
    )
    assert root_count == 2
    assert out_path == fragmented_session
    assert new_id is None
    assert fragmented_session.exists()
    assert fragmented_session.with_suffix(".jsonl.bak").exists()
