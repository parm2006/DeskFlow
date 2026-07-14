# Plan 006: Repair two-PC reliability and finish the compact security UI

> **Executor instructions**: Follow this plan in order and use red-green TDD for
> every behavior change. Do not touch background or daemon code. Stop at a
> design fork instead of hiding a failure with retries or generic error text.
>
> **Drift check (run first)**:
> `git diff 157b477 -- app tests docs/plans/security-revamp`
> Reconcile any in-scope drift before editing.

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001-005
- **Planned at**: revision `157b477`, 2026-07-13
- **Automated checkpoint**: complete; two-PC validation pending

## Why this matters

Two-PC testing proved the security foundation and restored transfer speed, but
it also exposed an intermittent reconnect failure, a repeat-paste stall, broken
remote Delete, excessive cursor inset, generic errors, missing role persistence,
and an oversized resizable window. These failures block the security revamp's
acceptance gate and must be fixed before background work begins.

## Current state

- `app/network.py` exposes typed pairing failures but collapses ordinary socket,
  timeout, and password failures at the client boundary.
- `app/client.py` prefixes failures with `Control Socket Error` or `Data Socket
  Error`, which describes implementation rather than the user's corrective
  action.
- `app/gui.py` schedules disconnect callbacks without tying them to the client
  instance that emitted them. A late callback can act on a newer connection.
- `app/file_transfer/publisher.py` owns an unbounded lifetime worker and retains
  clipboard owners indefinitely. A publish or paste-injection failure has no
  result path to the transfer controller.
- `app/input_geometry.py:1` uses a 96 px entry margin even though the input edge
  detector needs only a tiny safety inset.
- `app/input_handler.py` serializes Delete through the generic special-key path;
  no focused regression proves Windows receives the key while captured.
- `app/gui.py` uses `420x650`, enables resizing, and persists known hosts but not
  the last successfully started role.
- Test conventions use `unittest`, temporary directories for persistence, and
  observable callbacks/state rather than exported test-only helpers.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused tests | `.\venv\Scripts\python.exe -m unittest -q <test modules>` | all pass |
| Full tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | all pass |
| Compile | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |
| Whitespace | `git diff --check` | no output |

## Scope

**In scope**:

- `app/network.py`, `app/safe_errors.py`, `app/client.py`, `app/gui.py`
- `app/input_geometry.py`, `app/input_handler.py`
- `app/file_transfer/publisher.py`, `app/file_transfer/paste_service.py`, and
  transfer status/controller files only if required for a truthful failure path
- focused tests under `tests/`
- this effort index, validation plan, and results record

**Out of scope**:

- background mode, daemon processes, global hide/show shortcuts, packaging, and
  synchronized application exit
- protocol or encryption redesign unrelated to the observed failures

## Steps

### Step 1: Make connection outcomes actionable and generation-safe

Add caller-visible failure classes or tags for incorrect password, unreachable
server, connection timeout, pairing decline/timeout, changed identity, and lane
setup failure. Keep raw OS/TLS text out of the GUI. Make GUI callbacks carry or
capture their originating `DeskFlowClient`; ignore disconnect/connect results
from any object that is no longer current. Every attempt must finish once.

**Verify**: focused security-network, lifecycle, GUI, and error-redaction tests
all pass, including a stale old-client callback after a new client is installed.

### Step 2: Repair edge placement and Delete forwarding

Replace the 96 px entry margin with direction-specific coordinates just inside
the return threshold. Preserve ratio clamping along the perpendicular axis.
Characterize Delete serialization, transport, and injection through the real
`InputHandler` boundary. On Windows, use the smallest reliable native special-
key injection path if pynput's generic controller cannot represent Delete
reliably; do not special-case unrelated keys.

**Verify**: geometry tests prove all four entry coordinates cannot immediately
switch back, and input tests prove Delete press/release reaches the injector
without affecting Ctrl+V suppression.

### Step 3: Give virtual paste an owned lifecycle and failure contract

Make each queued paste produce a success/failure lifecycle owned by the
publisher. Catch failures per job so the worker survives. Bound the wait for
Explorer to begin consuming the advertised file, report timeout/failure through
the transfer controller, revoke obsolete clipboard ownership safely, and allow
the next job to proceed after success, failure, or cancellation. Do not impose a
deadline on an actively streaming large file.

**Verify**: tests cover two sequential successful publishes, publish failure
followed by success, paste-injection failure followed by success, Explorer-never-
opens timeout, cancellation followed by success, and bounded owner retention.

### Step 4: Persist successful role and make the root window compact

Store non-secret UI preferences under DeskFlow's local application-data root.
Save `server` only after a successful server start and `client` only after a
complete three-lane client connection. Failed attempts must not change it.
Restore the saved tab on startup. Use one compact fixed root size, disable
resizing/maximizing, and keep the selectable wrapping status panel visible.

**Verify**: temporary-store tests cover default, successful persistence, corrupt
preferences fallback, and failed-attempt non-persistence. Real-widget tests
cover fixed geometry, selected tab, status wrapping, and text selection.

### Step 5: Verify the integrated repair

Run focused tests after each red-green cycle, then the full suite, compileall,
and diff check. Confirm no daemon/background path changed. Update
`VALIDATION.md` only if implementation changes the required manual procedure.

## Test plan

- Extend `tests/test_security_error_redaction.py` and
  `tests/test_security_network.py` for typed, safe failure rendering.
- Add GUI lifecycle tests for stale callbacks and role-save timing.
- Replace the 96 px expectation in `tests/test_input_geometry.py` with safe-edge
  expectations and add focused Delete forwarding coverage.
- Extend `tests/test_file_paste_publisher.py` and lifecycle tests with sequential
  jobs, worker recovery, timeout, cancellation, and owner cleanup.
- Run all 181+ existing tests to detect protocol, transfer, or UI regressions.

## Done criteria

- [ ] Every reported defect has a regression that failed before its fix.
- [ ] Connection attempts never hang or fail silently and show actionable text.
- [ ] Sequential and post-cancel transfers recover without relaunching.
- [ ] Remote Delete uses a verified Windows injection path.
- [ ] Cursor entry is visually at the edge without bounce-back.
- [ ] Only the last successful role persists.
- [ ] The root is compact, fixed-size, non-resizable, and non-maximizable.
- [ ] Full test, compile, redaction, and diff gates pass.
- [ ] No background or daemon file changes.

## STOP conditions

Stop and write a handback if Windows Explorer requires retaining multiple OLE
owners after a completed drop, if reliable Delete injection requires a broader
input transport redesign, or if fixing reconnect requires changing the secure
session protocol rather than its GUI ownership boundary.

## Maintenance notes

Clipboard/OLE work must remain on its initialized STA thread. Connection
callbacks must never locate mutable global GUI state without verifying the
originating generation. Human-facing errors remain typed and safe; raw exception
text is diagnostic data and must not cross into the GUI.
