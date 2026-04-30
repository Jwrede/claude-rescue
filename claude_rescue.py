#!/usr/bin/env python3
"""claude-rescue: Diagnose and recover corrupted Claude Code session JSONL files."""

import argparse
import json
import os
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
                entry = json.loads(raw)
                entry["_lineno"] = lineno
                yield lineno, entry
            except json.JSONDecodeError:
                print(f"  warning: skipping malformed line {lineno} in {path.name}", file=sys.stderr)


def build_chains(entries: list[dict]) -> dict[str, list[dict]]:
    """
    Build chains from entries that have a uuid field.
    Returns a dict mapping root_uuid -> [list of entries in chain order].
    Entries without uuid are excluded from chain logic.
    """
    by_uuid: dict[str, dict] = {}
    children: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        uid = entry.get("uuid")
        if not uid:
            continue
        by_uuid[uid] = entry
        parent = entry.get("parentUuid")
        if parent:
            children[parent].append(uid)

    all_uuids = set(by_uuid.keys())
    child_uuids = set()
    for kids in children.values():
        child_uuids.update(kids)

    roots = all_uuids - child_uuids

    chains: dict[str, list[dict]] = {}
    for root in roots:
        chain = []
        stack = [root]
        while stack:
            current = stack.pop()
            if current not in by_uuid:
                continue
            chain.append(by_uuid[current])
            for child in children.get(current, []):
                stack.append(child)
        chains[root] = chain

    return chains


def count_broken_links(entries: list[dict]) -> int:
    """Count parentUuid references that point to non-existent uuids."""
    all_uuids = {e["uuid"] for e in entries if "uuid" in e}
    broken = 0
    for entry in entries:
        parent = entry.get("parentUuid")
        if parent and parent not in all_uuids:
            broken += 1
    return broken


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
        entries = [e for _, e in iter_jsonl(path)]
        chains = build_chains(entries)
        root_count = len(chains)
        broken = count_broken_links(entries)
        entry_count = len(entries)

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
    entries = [e for _, e in iter_jsonl(session_file)]
    chains = build_chains(entries)

    if not chains:
        print("No chains found — file may be empty or contain no valid entries.", file=sys.stderr)
        sys.exit(1)

    if len(chains) == 1:
        print("Session has only one chain — no recovery needed.")
        root = next(iter(chains))
        print(f"Session ID: {args.session_id}")
        return

    # Rank chains: highest max(_lineno) wins
    ranked = sorted(
        chains.items(),
        key=lambda kv: max((e.get("_lineno", 0) for e in kv[1]), default=0),
        reverse=True,
    )

    if args.pick:
        print(f"Found {len(ranked)} chains:\n")
        for i, (root, chain) in enumerate(ranked):
            max_line = max((e.get("_lineno", 0) for e in chain), default=0)
            # show a preview of the last entry's type/content
            last = max(chain, key=lambda e: e.get("_lineno", 0))
            preview = last.get("type") or last.get("role") or "(unknown)"
            print(f"  [{i + 1}] root={root[:8]}...  entries={len(chain)}  last_line={max_line}  last_type={preview}")

        print()
        while True:
            try:
                choice = int(input(f"Pick chain [1-{len(ranked)}]: "))
                if 1 <= choice <= len(ranked):
                    selected_root, selected_chain = ranked[choice - 1]
                    break
                print(f"Please enter a number between 1 and {len(ranked)}.")
            except (ValueError, EOFError):
                print("Invalid input.", file=sys.stderr)
                sys.exit(1)
    else:
        selected_root, selected_chain = ranked[0]

    # Gather non-uuid entries (metadata) to prepend
    meta_entries = [e for e in entries if "uuid" not in e]

    # Strip internal _lineno before writing
    def clean(e: dict) -> dict:
        return {k: v for k, v in e.items() if k != "_lineno"}

    output_entries = [clean(e) for e in meta_entries] + [clean(e) for e in selected_chain]

    new_id = str(uuid.uuid4())
    out_path = project_dir / f"{new_id}.jsonl"

    with open(out_path, "w", encoding="utf-8") as f:
        for entry in output_entries:
            f.write(json.dumps(entry) + "\n")

    print(f"Recovered {len(selected_chain)} entries ({len(meta_entries)} metadata lines) to:")
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
