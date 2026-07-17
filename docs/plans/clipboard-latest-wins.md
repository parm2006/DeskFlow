# Plan: Bound outbound clipboard work with latest-wins scheduling

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If a STOP condition occurs, stop and write a handback rather than improvising.
>
> **Drift check (run first)**: `git diff 8799e09 -- app/clipboard_handler.py app/client.py app/server.py app/latest_wins_sender.py tests/test_latest_wins_sender.py tests/test_clipboard_scheduling.py docs/superpowers/specs/2026-07-11-clipboard-reliability-phase-1-design.md`

## Status

- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Planned at**: revision `8799e09`, 2026-07-11

## Why this matters

Rapid screenshots can enqueue repeated compression and synchronous socket sends on the clipboard polling thread, making clipboard paste unavailable and possibly contributing to connection resets. This change bounds outbound work to one active and one replaceable pending snapshot while preserving the current rich clipboard payload schema.

## Current state

- `app/clipboard_handler.py:166-254` reads, compresses, and forwards clipboard content synchronously from its polling thread.
- `app/client.py:167-169` and `app/server.py:198-200` mutate the callback payload by adding `type`, then send it immediately.
- `app/latest_wins_sender.py:5-52` provides the initial one-active/one-pending worker.
- `tests/test_latest_wins_sender.py:7-34` proves A/B/C/D collapses to A/D.
- Tests use standard-library `unittest`; run them with the repository virtual environment.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused tests | `.\venv\Scripts\python.exe -m unittest tests.test_latest_wins_sender tests.test_clipboard_scheduling -v` | all tests pass |
| Full tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all tests pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

**In scope**:
- `app/latest_wins_sender.py`
- `app/clipboard_handler.py`
- `app/client.py`
- `app/server.py`
- `tests/test_latest_wins_sender.py`
- `tests/test_clipboard_scheduling.py`
- `docs/superpowers/specs/2026-07-11-clipboard-reliability-phase-1-design.md`

**Out of scope**:
- `app/network.py` — no wire-format or framing changes in this slice.
- `app/gui.py`, `app/input_handler.py`, `app/crypto.py` — unrelated behavior.
- Clipboard wipe policy, acknowledgements, message IDs, and TLS identity verification — deferred slices.

## Steps

### Step 1: Complete scheduler behavior under tests

Add failing tests for payload snapshotting, stopped-submission rejection/pending cancellation, and exception recovery. Make the smallest scheduler changes needed to pass without interrupting an active send.

**Verify**: `.\venv\Scripts\python.exe -m unittest tests.test_latest_wins_sender -v` → all scheduler tests pass.

### Step 2: Separate clipboard capture from encoding

Add tests around pure encoding behavior. Change `ClipboardHandler` so the Windows clipboard lock captures raw `text`, DIB, HTML, and RTF values, while zlib/Base64 encoding occurs in a separate callable outside the polling thread. Preserve existing keys and codecs.

**Verify**: `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_scheduling -v` → encoding compatibility tests pass.

### Step 3: Integrate one sender per peer

Add failing client/server tests using lightweight fakes or construction without OS hooks. Each peer must submit captured snapshots to its sender; the worker must encode a fresh message and call the data network without mutating caller-owned dictionaries. Stop/disconnect must stop the sender idempotently.

**Verify**: `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_scheduling -v` → routing and shutdown tests pass.

### Step 4: Run complete automated verification

Run full tests and syntax compilation. Inspect the diff for accidental protocol or unrelated changes.

**Verify**: `.\venv\Scripts\python.exe -m unittest discover -s tests -v` and `.\venv\Scripts\python.exe -m compileall -q app tests` → exit 0.

## Test plan

- Extend `tests/test_latest_wins_sender.py` for concurrency and lifecycle behavior.
- Create `tests/test_clipboard_scheduling.py` for encoding compatibility and peer routing.
- Avoid a live GUI, physical input hooks, and the actual Windows clipboard where pure collaborators can be tested.
- Manual two-machine rapid-screenshot testing remains required after automated verification.

## Done criteria

- [ ] One active plus one replaceable pending outbound snapshot.
- [ ] Polling thread does not compress or send clipboard data.
- [ ] Existing text/image/HTML/RTF schema remains compatible.
- [ ] Full test discovery passes.
- [ ] Compileall passes.
- [ ] No out-of-scope files modified.

## STOP conditions

Stop if existing payload compatibility requires changing `app/network.py`, if Windows clipboard ownership requires encoding while the clipboard is open, or if client/server lifecycle cannot safely own a reusable sender without a broader connection-state redesign.

## Maintenance notes

Future protocol work should treat the scheduler as transport backpressure, not delivery confirmation. The two-machine test must capture logs from both peers before attributing `[WinError 10054]` to this issue.
