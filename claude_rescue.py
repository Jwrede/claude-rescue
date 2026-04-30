#!/usr/bin/env python3
"""claude-rescue: Diagnose and recover corrupted Claude Code session JSONL files."""

import argparse
import gc
import json
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path

# Extracts "uuid" and "parentUuid" from a raw JSONL line without full JSON parse.
# Safe because these fields are always plain strings (no escapes needed).
_RE_UUID = re.compile(rb'"uuid"\s*:\s*"([^"]+)"')
_RE_PARENT = re.compile(rb'"parentUuid"\s*:\s*"([^"]+)"')


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
    First pass: extract only uuid/parentUuid via regex on raw bytes — no JSON parse.
    Returns (children, last_lineno_by_uuid, meta_count).
    """
    children: dict[str, list[str]] = defaultdict(list)
    last_lineno: dict[str, int] = {}
    meta_count = 0

    with open(path, "rb") as f:
        for lineno, raw in enumerate(f):
            raw = raw.strip()
            if not raw:
                continue
            m = _RE_UUID.search(raw)
            if not m:
                meta_count += 1
                continue
            uid = m.group(1).decode()
            last_lineno[uid] = lineno
            mp = _RE_PARENT.search(raw)
            if mp:
                parent = mp.group(1).decode()
                if parent != "null":
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

    # Group by first-level project dir, stable-sort within each group by path.
    def sort_key(p: Path) -> tuple[str, Path]:
        return (p.relative_to(base).parts[0], p)

    files = sorted(files, key=sort_key)

    col_w = [36, 20, 7, 6, 7, 12]
    header = (
        f"  {'Session ID':<{col_w[0]}}  "
        f"{'Subdir':<{col_w[1]}}  "
        f"{'Entries':>{col_w[2]}}  "
        f"{'Roots':>{col_w[3]}}  "
        f"{'Broken':>{col_w[4]}}  "
        f"{'Status':<{col_w[5]}}"
    )
    rule = "  " + "-" * (len(header) - 2)

    current_project: str | None = None

    for path in files:
        parts = path.relative_to(base).parts
        project = parts[0]
        # subdir: everything between the project root and the file itself
        subdir = "/".join(parts[1:-1]) if len(parts) > 2 else ""
        subdir_display = (subdir[:17] + "...") if len(subdir) > 20 else subdir

        if project != current_project:
            current_project = project
            print(f"\n{project}/")
            print(header)
            print(rule)

        session_id = path.stem
        entry_count, root_count, broken = diagnose_file(path)

        if broken > 0:
            status = "✗ corrupted"
        elif root_count > 1:
            status = "⚠ fragmented"
        else:
            status = "✓ healthy"

        print(
            f"  {session_id:<{col_w[0]}}  "
            f"{subdir_display:<{col_w[1]}}  "
            f"{entry_count:>{col_w[2]}}  "
            f"{root_count:>{col_w[3]}}  "
            f"{broken:>{col_w[4]}}  "
            f"{status:<{col_w[5]}}"
        )


def _recover_file(
    session_file: Path,
    project_dir: Path,
    pick: bool = False,
    in_place: bool = False,
) -> tuple[int, int, int, Path | None, str | None]:
    """
    Run the two-pass recovery on session_file.
    Returns (root_count, written_entries, written_meta, out_path, new_id).
    out_path/new_id are None if root_count <= 1 (no recovery needed).
    """
    children, last_lineno, _meta_count = _build_chain_index(session_file)

    if not last_lineno:
        return 0, 0, 0, None, None

    all_uuids = set(last_lineno.keys())
    child_uuids: set[str] = set()
    for kids in children.values():
        child_uuids.update(kids)
    root_count = len(all_uuids - child_uuids)

    if root_count <= 1:
        return root_count, 0, 0, None, None

    selected_uuids, _ranked = _find_best_chain(children, last_lineno, pick)

    if in_place:
        bak_path = session_file.with_suffix(".jsonl.bak")
        session_file.rename(bak_path)
        out_path = session_file
        new_id = None
    else:
        new_id = str(uuid.uuid4())
        out_path = project_dir / f"{new_id}.jsonl"
        bak_path = session_file

    written_meta = 0
    written_entries = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for _lineno, entry in iter_jsonl(bak_path):
            uid = entry.get("uuid")
            if not uid:
                f.write(json.dumps(entry) + "\n")
                written_meta += 1
            elif uid in selected_uuids:
                f.write(json.dumps(entry) + "\n")
                written_entries += 1

    return root_count, written_entries, written_meta, out_path, new_id


def cmd_recover(args):
    result = find_session_file(args.session_id, args.project)
    if result is None:
        print(f"Session file not found for ID: {args.session_id}", file=sys.stderr)
        sys.exit(1)

    project_dir, session_file = result
    root_count, written_entries, written_meta, out_path, new_id = _recover_file(
        session_file, project_dir, pick=args.pick
    )

    if root_count == 0:
        print("No chains found — file may be empty or contain no valid entries.", file=sys.stderr)
        sys.exit(1)

    if out_path is None:
        print("Session has only one chain — no recovery needed.")
        print(f"Session ID: {args.session_id}")
        return

    print(f"Recovered {written_entries} entries ({written_meta} metadata lines) to:")
    print(f"  {out_path}")
    if new_id:
        print()
        print(f"Resume with:")
        print(f"  claude --resume {new_id}")


def cmd_recover_all(args):
    base = find_project_dir(args.project_path)
    if not base.exists():
        print(f"Directory not found: {base}", file=sys.stderr)
        sys.exit(1)

    files = sorted(
        f for f in base.rglob("*.jsonl")
        if not f.name.endswith(".bak") and not f.name.endswith(".recovered.jsonl")
    )

    recovered = skipped = errors = 0

    for session_file in files:
        session_id = session_file.stem
        is_acompact = "acompact" in session_id
        in_place = is_acompact or args.in_place

        try:
            root_count, written_entries, written_meta, out_path, new_id = _recover_file(
                session_file, session_file.parent, in_place=in_place
            )
        except Exception as e:
            print(f"  error: {session_id}: {e}", file=sys.stderr)
            errors += 1
            gc.collect()
            continue

        gc.collect()

        if out_path is None:
            skipped += 1
            continue

        recovered += 1
        if in_place:
            print(f"  recovered (in-place): {session_id}  ({written_entries} entries)")
        else:
            print(f"  recovered: {session_id} -> {new_id}  ({written_entries} entries)")
            if not args.quiet:
                print(f"    resume with: claude --resume {new_id}")

    print(f"\nDone: {recovered} recovered, {skipped} already healthy, {errors} errors.")


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

    # recover-all
    p_all = sub.add_parser("recover-all", help="Recover all fragmented sessions in batch.")
    p_all.add_argument(
        "project_path",
        nargs="?",
        default=None,
        metavar="PROJECT_PATH",
        help=f"Directory to scan (default: {PROJECTS_DIR})",
    )
    p_all.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite originals (backup as .bak) instead of writing new UUID files. "
             "Always used automatically for agent-acompact-* files.",
    )
    p_all.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file resume hints.",
    )
    p_all.set_defaults(func=cmd_recover_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
