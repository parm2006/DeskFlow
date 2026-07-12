# Plan 002: Mirror measured Explorer-consumed progress to both toasts

> **Executor instructions**: Follow every step and verification gate. Stop and write a handback at any listed fork. Update `README.md` when done.
>
> **Drift check (run first)**: `git diff afcdbba -- app/windows_virtual_files.py app/file_transfer/publisher.py app/file_transfer/receiver.py app/file_transfer/sender.py app/file_transfer/status.py app/file_transfer/controller.py app/file_transfer/toast.py app/file_transfer/protocol.py app/file_transfer/transport.py tests/test_windows_virtual_files.py tests/test_file_paste_publisher.py tests/test_file_transfer_receiver.py tests/test_file_transfer_sender.py tests/test_file_transfer_status.py tests/test_file_transfer_toast.py tests/test_file_transfer_protocol.py tests/test_file_transfer_transport.py`

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001-fix-toast-monitor-placement.md
- **Planned at**: revision `afcdbba`, 2026-07-12

## Why this matters

DeskFlow reaches 100% when bytes are staged, while Explorer may still be waiting on a conflict dialog or writing the file. Progress must instead count bytes Explorer actually receives from the virtual `IStream`. The destination owns this measurement and must mirror it to the source.

## Current state

- `app/windows_virtual_files.py:275-337` implements `CallbackStream.Read`, `Seek`, and `Clone` without consumption callbacks.
- `app/file_transfer/publisher.py:16-36` opens each virtual stream through `receiver.read_range`.
- `app/file_transfer/receiver.py:114-144` serves staged ranges; `complete_job` currently declares completion after network verification.
- `app/file_transfer/sender.py:16-18` registers file-lane callbacks and can consume destination-owned status events.
- `app/file_transfer/status.py:5-19` lacks waiting, Explorer-paste, verifying-result, and cancelling phases.
- File-lane metadata is bounded by `app/file_transfer/protocol.py`; callback dispatch follows `app/file_transfer/transport.py:50-76`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Stream tests | `.\venv\Scripts\python.exe -m unittest tests.test_windows_virtual_files tests.test_file_paste_publisher -v` | all pass |
| Progress tests | `.\venv\Scripts\python.exe -m unittest tests.test_file_transfer_receiver tests.test_file_transfer_sender tests.test_file_transfer_status tests.test_file_transfer_toast -v` | all pass |
| Protocol tests | `.\venv\Scripts\python.exe -m unittest tests.test_file_transfer_protocol tests.test_file_transfer_transport -v` | all pass |
| Full suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

**In scope**: files named by the drift check plus a focused new module such as `app/file_transfer/range_coverage.py` and its test.

**Out of scope**: native `IDataObjectAsyncCapability`, Explorer-window detection, destination-toast hiding, bandwidth-policy changes, and user-facing queue support.

## Steps

### Step 1: Account for unique consumed ranges

Test-first, add a thread-safe range coverage component per file. It must merge overlapping and adjacent intervals, ignore rereads, accept out-of-order reads, reject negative or beyond-size ranges, and report a monotonic union length. Test stream seeks and clones against shared coverage state.

Extend `CallbackStream` and `open_callback_stream` with an optional `on_read(offset, returned_count)` callback. Invoke it only after bytes are successfully returned. Clones must share the same logical progress callback.

**Verify**: stream tests pass.

### Step 2: Separate network verification from Explorer completion

Add explicit phases: `RECEIVING`, `WAITING_FOR_EXPLORER`, `PASTING`, `VERIFYING_RESULT`, and `CANCELLING`. Network hash verification transitions to waiting instead of terminal completion. `build_virtual_file_set` connects each stream read to a receiver-owned consumption tracker for the manifest job.

Directories contribute zero bytes. A zero-byte-only job may complete consumption immediately but must still wait for the lifecycle result in Plan 003 when that capability is available.

**Verify**: progress tests pass with new assertions that staging 100% is nonterminal.

### Step 3: Send bounded destination-owned progress

Define and validate `paste_progress` metadata containing only job ID, phase, covered bytes, total bytes, and measured rate. Rate-limit emission using both a byte threshold and a maximum update interval; always emit phase changes and terminal-relevant boundaries. Never block Explorer's COM callback on UI work.

The source sender registers a callback and applies only monotonic, matching-total events for an active known job. Ignore duplicates and stale events; reject impossible totals without killing the file lane.

**Verify**: protocol and transport tests pass, including malformed, stale, duplicate, and unknown-job events.

### Step 4: Drive both toasts from Explorer progress

Update toast copy for receiving, waiting, and copying phases. Both peers show the same Explorer-consumption percentage once reads start. Waiting uses an indeterminate bar. Do not infer progress from configured bandwidth. Preserve measured network progress as an earlier labeled stage.

Until Plan 003 lands, full unique read coverage is the fallback completion signal. Record that fallback distinction in logs and tests; user-facing text may say `Copied by Explorer` only after full coverage.

**Verify**: all focused tests, full suite, and syntax pass.

## Test plan

Use real `CallbackStream` reads where possible. Test overlapping reads, clones, seeks, multi-file totals, zero-byte files, concurrent updates, rate limiting, malformed frames, and a conflict-dialog simulation where network staging finishes before any Explorer read.

## Done criteria

- [ ] Toast progress never advances Explorer-stage bytes before `IStream.Read` returns them.
- [ ] Both peers converge on the same monotonic destination-owned progress.
- [ ] Network verification is nonterminal.
- [ ] Progress events are bounded, privacy-safe, and rate-limited.
- [ ] Full suite and syntax pass.

## STOP conditions

Stop if Explorer reads cannot be observed without blocking its COM thread, clones cannot share coverage safely, progress messages contend with file chunks enough to affect input, or a protocol change requires absolute paths. Stop at any completion-semantics fork not covered by the approved design.

## Maintenance notes

Plan 003 replaces fallback full-read completion with Explorer's reported lifecycle result. Keep range accounting because it remains the source of progress values.
