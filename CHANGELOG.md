# Changelog

## [0.2.1] - 2026-05-01

### Fixed
- `diagnose`, `recover`, and `recover-all` now show the *last* `lastPrompt` value in the session, matching the title displayed by `claude resume`. Previously the first occurrence was shown, which reflected an early state of the conversation.

## [0.2.0] - 2026-04-30

### Added
- `prune-acompact` command to delete compaction sidechain files and reclaim disk space
- `--version` flag
- `--dry-run` flag for `prune-acompact`
- Duplicate recovery detection: `recover` and `recover-all` skip re-recovering a session whose chain hasn't changed, returning the existing session ID instead
- Last prompt printed in `recover` and `recover-all` output so you know which conversation is being processed
- `diagnose` and `recover-all` now default to the current directory instead of scanning all projects
- `diagnose .` resolves the current working directory to its Claude project folder automatically
- Sessions grouped by project in `diagnose` output
- Last prompt shown as title column in `diagnose` output
- Subagent files hidden by default in `diagnose` (use `--subagents` to show them)

### Changed
- `recover-all` automatically uses in-place recovery for `agent-acompact-*` files
- First pass of recovery now uses raw-byte regex extraction instead of `json.loads`, reducing peak memory from ~500 MB to ~11 MB on large sessions
- Explicit `gc.collect()` between files in `recover-all` to prevent memory accumulation

## [0.1.0] - 2026-04-30

### Added
- Initial release
- `diagnose` command: scan session files and report health (healthy / fragmented / corrupted)
- `recover` command: recover the best chain from a fragmented or corrupted session
- `recover-all` command: batch recover all fragmented sessions in a directory
- Two-pass recovery: first pass indexes only UUIDs, second pass streams entries — avoids loading full session into memory
