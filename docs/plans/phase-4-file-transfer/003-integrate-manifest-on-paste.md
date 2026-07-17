# Plan 003: Integrate manifest-on-paste file jobs

> Preserve current mouse, keyboard, and rich clipboard behavior. Use test-first key-state and routing tests before wiring OS hooks.
>
> **Drift check**: `git diff d352936 -- app/input_handler.py app/clipboard_handler.py app/client.py app/server.py app/windows_virtual_files.py app/file_transfer tests`

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001, 002
- **Planned at**: `d352936`, 2026-07-11

## Why this matters

Remote paste—not local copy—must prove intent. The manifest handshake briefly suppresses new copy operations, then the accepted job becomes independent so later clipboard and input activity continues normally.

## Current state

- File clipboard format `CF_HDROP` is not captured.
- `app/server.py:168-197` tracks keys and forwards them immediately.
- `app/client.py:148-156` injects received keys immediately.
- Rich clipboard uses latest-wins scheduling and must remain independent.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_file_paste*.py" -v` | all pass |
| Full | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

In scope: file-format capture additions, a paste coordinator, minimal client/server/input routing, virtual-file integration, and focused tests.

Out of scope: arbitrary third-party paste targets, cut/delete semantics, network redesign beyond Plan 002, and UI beyond status events.

## Steps

1. Detect `CF_HDROP` without sending or manifesting files on copy. Ordinary text/image/HTML/RTF behavior remains unchanged.
2. When control is remote and `Ctrl+V` occurs, suppress that paste and send a manifest request to the source peer. Temporarily suppress new `Ctrl+C` only during the handshake, with a hard one-second timeout.
3. Source snapshots the current file selection into an immutable manifest. Receiver validates and acknowledges only after creating a FIFO TransferJob; failure releases suppression, creates no job, and reports retryable status.
4. Bind the accepted job to the virtual data object from Plan 001 and let Explorer/Desktop consume streams. After acknowledgement, release clipboard/key suppression immediately; subsequent clipboard changes and file pastes proceed independently.
5. Ensure repeated file pastes create FIFO jobs rather than replacing one another. Ordinary clipboard traffic and input remain parallel.
6. Treat Cut as Copy; never delete source files. Fail clearly if a source is renamed, deleted, modified incompatibly, or unreadable before completion.

## Test plan

Cover Ctrl state variants, one-second timeout, manifest immutability, copy immediately after paste, screenshot/text during file streaming, multiple FIFO file pastes, clipboard changes after job creation, both server→client and client→server direction, disconnect cleanup, and no accidental forwarding of suppressed key events.

## Done criteria

- [x] No file bytes transfer before remote Ctrl+V.
- [x] Manifest handshake completes or fails within one second.
- [x] Clipboard and input are free immediately after job acceptance.
- [x] Multiple initiated file transfers are preserved in FIFO order by a single-writer executor.
- [x] Explorer and Desktop paste complete while later text/screenshot clipboard operations work.
- [x] Existing clipboard tests and all new tests pass.

## Verification record

- **2026-07-12 automated**: 83 repository tests passed; FIFO execution test proves B and C remain pending while A is active, then run A → B → C without overlap.
- **2026-07-12 manual**: server→client and client→server passed with small and 100 MB files, mixed multi-file selections, folders, Desktop and Explorer destinations, screenshots/text during transfer, disconnect/reconnect, repeated filenames, and cut treated as copy.
- **Accepted limitation**: the active Explorer window remains synchronously busy while its virtual stream is being consumed. Selecting multiple files/folders in one paste works, but navigating that same Explorer window to initiate additional destination-specific pastes before completion is deferred to [GitHub issue #1](https://github.com/parm2006/DeskFlow/issues/1). The proposed fix is a native data object implementing `IDataObjectAsyncCapability`.

## STOP conditions

Stop if the source clipboard cannot be read reliably during the handshake, suppression loses modifier releases, or Explorer requires behavior inconsistent with Plan 001 evidence.

## Maintenance notes

The paste coordinator owns intent and key suppression; the transfer engine owns bytes; the virtual data object owns Windows consumption. Do not merge these responsibilities.
