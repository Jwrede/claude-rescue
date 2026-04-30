# claude-rescue

Diagnose and recover corrupted or fragmented [Claude Code](https://claude.ai/code) session files.

Claude Code stores conversations as JSONL files in `~/.claude/projects/`. Over time these files can become **fragmented** (multiple disconnected conversation chains in one file, usually from interrupted sessions or reconnects) or **corrupted** (entries referencing parents that don't exist). `claude-rescue` finds these issues and recovers the best chain so you can resume with full context.

## Installation

```bash
pipx install claude-rescue   # recommended
# or
pip install claude-rescue
```

## Commands

### `diagnose`

Scan a project directory and report the health of each session file.

```bash
claude-rescue diagnose          # current directory (auto-resolved to its Claude project)
claude-rescue diagnose .        # same
claude-rescue diagnose ~/work/my-project
claude-rescue diagnose --subagents   # also show subagent/compaction files
```

Example output:
```
(project root)
  Session ID                            Entries   Roots   Broken  Status        Last prompt
  ---------------------------------------------------------------------------------------------------------------
  69e982d2-71f2-447a-a4df-1f90ae590e2d    8682      57        0  ⚠ fragmented  please familiarise yourself with...
  fbf21b51-e264-4721-adf8-d176907d8404    1824       1        0  ✓ healthy     can you add error handling to...
```

**Status meanings:**
- `✓ healthy` — single chain, no issues
- `⚠ fragmented` — multiple disconnected chains; recoverable
- `✗ corrupted` — entries with missing parents; recoverable (dangling entries are dropped)

### `recover`

Recover a single session by ID, keeping the most recently written chain.

```bash
claude-rescue recover 69e982d2-71f2-447a-a4df-1f90ae590e2d
```

Output:
```
Last prompt: please familiarise yourself with this project

Recovered 57 entries (1769 metadata lines) to:
  /home/you/.claude/projects/.../1892d453-aa34-4598-80c0-e214234e0c7d.jsonl

Resume with:
  claude --resume 1892d453-aa34-4598-80c0-e214234e0c7d
```

Options:
- `--pick` — interactively choose which chain to recover instead of auto-selecting
- `--project PATH` — specify the project directory if not auto-detected

Running `recover` twice on the same session without changes prints the existing ID instead of creating a duplicate.

### `recover-all`

Recover every fragmented or corrupted session in a directory.

```bash
claude-rescue recover-all          # current directory
claude-rescue recover-all ~/work/my-project
claude-rescue recover-all --quiet  # suppress per-file resume hints
claude-rescue recover-all --in-place  # overwrite originals (backup as .bak)
```

Compaction files (`agent-acompact-*`) are always recovered in-place since they have no session ID to resume.

### `prune-acompact`

Delete compaction sidechain files (`agent-acompact-*`). These are internal transcripts of Claude's context-summarisation runs and are not needed for resuming sessions — the summary itself is stored inline in the main session file.

```bash
claude-rescue prune-acompact            # current directory
claude-rescue prune-acompact --dry-run  # show what would be deleted
```

On a long-running project this can recover hundreds of MB.

## How it works

Claude Code session files are JSONL where each entry has a `uuid` and optional `parentUuid`, forming a linked chain. Fragmentation occurs when multiple root entries (entries with no parent) exist in the same file — typically after a reconnect writes a new root instead of continuing from the last entry.

`claude-rescue` uses a two-pass approach:

1. **Pass 1** — extract only `uuid`/`parentUuid` via raw-byte regex (no full JSON parse). Builds the chain tree in ~10 MB of memory regardless of file size.
2. **Pass 2** — stream the file again, writing only entries belonging to the selected chain.

The best chain is selected by highest last-written line number (most recently active chain). Use `--pick` to override.

## Contributing

Issues and pull requests welcome at [github.com/Jwrede/claude-rescue](https://github.com/Jwrede/claude-rescue).
