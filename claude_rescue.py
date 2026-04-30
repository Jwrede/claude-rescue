#!/usr/bin/env python3
"""claude-rescue: Diagnose and recover corrupted Claude Code session JSONL files."""

import argparse
import json
import sys
import uuid
from collections import defaultdict
from pathlib import Path


PROJECTS_DIR = Path.home() / ".claude" / "projects"


def iter_jsonl(path: Path):
    """Yield (lineno, parsed_dict) for each valid line, warning on malformed ones."""
    with open(path, "r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield lineno, json.loads(raw)
            except json.JSONDecodeError:
                print(f"  warning: skipping malformed line {lineno} in {path.name}", file=sys.stderr)


def diagnose_file(path: Path) -> tuple[int, int, int]:
    """
    Stream through a file and return (entry_count, root_count, broken_count).
    Only keeps uuid/parentUuid strings in memory — not full entry dicts.
    """
    uuids: set[str] = set()
    parents: dict[str, str] = {}  # uuid -> parentUuid
    entry_count = 0

    for _lineno, entry in iter_jsonl(path):
        entry_count += 1
        uid = entry.get("uuid")
        if not uid:
            continue
        uuids.add(uid)
        parent = entry.get("parentUuid")
        if parent:
            parents[uid] = parent

    child_uuids = set(parents.values()) & uuids
    root_count = len(uuids - child_uuids)

    broken = sum(1 for p in parents.values() if p not in uuids)

    return entry_count, root_count, broken


def _build_chain_index(path: Path) -> tuple[dict[str, list[str]], dict[str, int], int]:
    """
    First pass: read only uuid/parentUuid to build the chain structure.
    Returns (children, last_lineno_by_uuid, meta_count).
    last_lineno_by_uuid tracks the highest line number seen for each uuid
    (used to rank chains by recency without storing full entries).
    """
    children: dict[str, list[str]] = defaultdict(list)
    last_lineno: dict[str, int] = {}
    meta_count = 0

    for lineno, entry in iter_jsonl(path):
        uid = entry.get("uuid")
        if not uid:
            meta_count += 1
            continue
        last_lineno[uid] = lineno
        parent = entry.get("parentUuid")
        if parent:
            children[parent].append(uid)

    return children, last_lineno, meta_count


def _find_best_chain(
    children: dict[str, list[str]],
    last_lineno: dict[str, int],
    pick: bool,
) -> tuple[set[str], list[tuple[str, int, int]]]:
    """
    Walk the chain tree (index only) and return (best_uuid_set, ranked_summaries).
    ranked_summaries: [(root_uuid, entry_count, max_lineno), ...] highest-recency first.
    """
    all_uuids = set(last_lineno.keys())
    child_uuids: set[str] = set()
    for kids in children.values():
        child_uuids.update(kids)
    roots = all_uuids - child_uuids

    summaries: list[tuple[str, int, int]] = []
    for root in roots:
        stack = [root]
        chain_uuids: list[str] = []
        while stack:
            cur = stack.pop()
            if cur not in last_lineno:
                continue
            chain_uuids.append(cur)
            for child in children.get(cur, []):
                stack.append(child)
        max_ln = max((last_lineno[u] for u in chain_uuids), default=0)
        summaries.append((root, len(chain_uuids), max_ln))

    ranked = sorted(summaries, key=lambda t: t[2], reverse=True)

    if pick and len(ranked) > 1:
        print(f"Found {len(ranked)} chains:\n")
        for i, (root, count, max_ln) in enumerate(ranked):
            print(f"  [{i + 1}] root={root[:8]}...  entries={count}  last_line={max_ln}")
        print()
        while True:
            try:
                choice = int(input(f"Pick chain [1-{len(ranked)}]: "))
                if 1 <= choice <= len(ranked):
                    selected_root, _, _ = ranked[choice - 1]
                    break
                print(f"Please enter a number between 1 and {len(ranked)}.")
            except (ValueError, EOFError):
                print("Invalid input.", file=sys.stderr)
                sys.exit(1)
    else:
        selected_root = ranked[0][0]

    # Collect the uuid set for the selected chain
    stack = [selected_root]
    selected_uuids: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur not in last_lineno:
            continue
        selected_uuids.add(cur)
        for child in children.get(cur, []):
            stack.append(child)

    return selected_uuids, ranked


def find_project_dir(project_path: str | None) -> Path:
    if project_path:
        return Path(project_path).expanduser()
    return PROJECTS_DIR


def find_session_file(session_id: str, project_path: str | None) -> tuple[Path, Path] | None:
    """Return (project_dir, session_file) for the given session ID."""
    base = find_project_dir(project_path)
    if not base.exists():
        return None
    for jsonl in base.rglob("*.jsonl"):
        if jsonl.name.endswith(".bak") or jsonl.name.endswith(".recovered.jsonl"):
            continue
        if jsonl.stem == session_id:
            return jsonl.parent, jsonl
    return None


def cmd_diagnose(args):
    base = find_project_dir(args.project_path)
    if not base.exists():
        print(f"Directory not found: {base}", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        f for f in base.rglob("*.jsonl")
        if not f.name.endswith(".bak") and not f.name.endswith(".recovered.jsonl")
    )

    if not files:
        print("No session files found.")
        return

    col_w = [36, 7, 6, 7, 12]
    header = (
        f"{'Session ID':<{col_w[0]}}  "
        f"{'Entries':>{col_w[1]}}  "
        f"{'Roots':>{col_w[2]}}  "
        f"{'Broken':>{col_w[3]}}  "
        f"{'Status':<{col_w[4]}}"
    )
    print(header)
    print("-" * len(header))

    for path in files:
        session_id = path.stem
        entry_count, root_count, broken = diagnose_file(path)

        if broken > 0:
            status = "✗ corrupted"
        elif root_count > 1:
            status = "⚠ fragmented"
        else:
            status = "✓ healthy"

        print(
            f"{session_id:<{col_w[0]}}  "
            f"{entry_count:>{col_w[1]}}  "
            f"{root_count:>{col_w[2]}}  "
            f"{broken:>{col_w[3]}}  "
            f"{status:<{col_w[4]}}"
        )


def cmd_recover(args):
    result = find_session_file(args.session_id, args.project)
    if result is None:
        print(f"Session file not found for ID: {args.session_id}", file=sys.stderr)
        sys.exit(1)

    project_dir, session_file = result

    # Pass 1: build chain index from uuid/parentUuid only (no full entry storage)
    children, last_lineno, meta_count = _build_chain_index(session_file)

    if not last_lineno:
        print("No chains found — file may be empty or contain no valid entries.", file=sys.stderr)
        sys.exit(1)

    all_uuids = set(last_lineno.keys())
    child_uuids: set[str] = set()
    for kids in children.values():
        child_uuids.update(kids)
    root_count = len(all_uuids - child_uuids)

    if root_count <= 1:
        print("Session has only one chain — no recovery needed.")
        print(f"Session ID: {args.session_id}")
        return

    selected_uuids, ranked = _find_best_chain(children, last_lineno, args.pick)

    # Pass 2: stream the file again, writing only selected entries
    new_id = str(uuid.uuid4())
    out_path = project_dir / f"{new_id}.jsonl"

    written_meta = 0
    written_entries = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for _lineno, entry in iter_jsonl(session_file):
            uid = entry.get("uuid")
            if not uid:
                f.write(json.dumps(entry) + "\n")
                written_meta += 1
            elif uid in selected_uuids:
                f.write(json.dumps(entry) + "\n")
                written_entries += 1

    print(f"Recovered {written_entries} entries ({written_meta} metadata lines) to:")
    print(f"  {out_path}")
    print()
    print(f"Resume with:")
    print(f"  claude --resume {new_id}")


def main():
    parser = argparse.ArgumentParser(
        prog="claude-rescue",
        description="Diagnose and recover corrupted Claude Code session JSONL files.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # diagnose
    p_diag = sub.add_parser("diagnose", help="Scan session files and report health.")
    p_diag.add_argument(
        "project_path",
        nargs="?",
        default=None,
        metavar="PROJECT_PATH",
        help=f"Directory to scan (default: {PROJECTS_DIR})",
    )
    p_diag.set_defaults(func=cmd_diagnose)

    # recover
    p_rec = sub.add_parser("recover", help="Recover the best chain from a fragmented session.")
    p_rec.add_argument("session_id", metavar="SESSION_ID")
    p_rec.add_argument(
        "--pick",
        action="store_true",
        help="Interactively choose which chain to recover.",
    )
    p_rec.add_argument(
        "--project",
        default=None,
        metavar="PROJECT_PATH",
        help="Project directory containing the session file.",
    )
    p_rec.set_defaults(func=cmd_recover)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
