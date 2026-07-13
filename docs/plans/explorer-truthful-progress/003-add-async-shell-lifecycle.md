# Plan 003: Use Explorer's async lifecycle as the authoritative paste result

> **Executor instructions**: Treat this as a high-risk Windows integration. Run every gate. Stop on toolchain, ABI, COM lifetime, or packaging uncertainty; do not improvise a different bridge architecture.
>
> **Drift check (run first)**: `git diff afcdbba -- app/windows_virtual_files.py app/file_transfer/publisher.py app/file_transfer/status.py app/file_transfer/controller.py app/file_transfer/toast.py requirements.txt run.bat native tests`

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 002-report-explorer-consumed-progress.md
- **Planned at**: revision `afcdbba`, 2026-07-12

## Why this matters

Full `IStream.Read` coverage is strong evidence that Explorer consumed the bytes, but only `IDataObjectAsyncCapability.EndOperation` reports the Shell operation's final HRESULT. pywin32 exposes no built-in server gateway for that interface. A narrow native bridge supplies the missing COM lifecycle without moving networking, staging, validation, or UI into native code.

## Current state

- `app/windows_virtual_files.py:99-204` exposes only `IDataObject` through pywin32.
- No `native/` build, C/C++ compiler command, extension packaging, or CI job exists.
- `requirements.txt` includes pywin32 and PyInstaller, but the repository has no application spec file.
- The approved interface and state semantics live in `docs/superpowers/specs/2026-07-12-explorer-truthful-progress-design.md`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Toolchain probe | `where.exe cl` | one MSVC compiler path; otherwise STOP |
| Native tests | `.\venv\Scripts\python.exe -m unittest tests.test_shell_async_bridge -v` | all pass |
| Python suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

No native build command exists at planning time. Establishing one reproducible command is Step 1 and a required deliverable.

## Scope

**In scope**: a new `native/shell_async_bridge/` boundary, its deterministic build definition, a small Python adapter under `app/file_transfer/`, publisher/data-object integration, packaging metadata, and focused tests.

**Out of scope**: moving TLS or file I/O policy into native code, registering a machine-wide COM server, Explorer UI automation, suppressing Explorer-owned error dialogs, and issue #2.

## Steps

### Step 1: Establish a reproducible bridge build

Probe MSVC availability. Add one repository-owned build command that produces a same-architecture Python-loadable module or local helper without administrator registration. Document compiler and Windows SDK prerequisites. The artifact must build outside the source tree and be ignored by Git.

**Verify**: run the new build command twice from a clean artifact directory; both runs exit 0. If MSVC or required SDK headers are unavailable, STOP with exact probe output.

### Step 2: Prove COM negotiation in isolation

Implement only `IUnknown`, `IDataObject` delegation, and `IDataObjectAsyncCapability` lifecycle methods. Keep callbacks thread-safe and nonblocking. Add a diagnostic test harness that queries the published object for both interfaces and exercises `SetAsyncMode`, `GetAsyncMode`, `StartOperation`, `InOperation`, and `EndOperation` with success and failure HRESULTs.

Do not integrate Explorer until reference counting and QueryInterface tests pass under repeated creation and release.

**Verify**: native bridge tests pass without leaked references or process crashes.

### Step 3: Map lifecycle events into the existing state model

Connect Start/End callbacks to the destination controller and authenticated peer status. `EndOperation(S_OK)` is the authoritative completed state. An error after a user-initiated DeskFlow cancellation maps to cancelled; other HRESULTs map to failed using privacy-safe stable error codes. Terminal states remain immutable.

Retain Plan 002's full-read fallback when Explorer declines async mode. Log whether completion was authoritative or fallback without exposing paths.

**Verify**: lifecycle mapping tests and the full Python suite pass.

### Step 4: Package and run the two-computer matrix

Ensure `run.bat` development startup and the supported packaged build can locate the bridge on both PCs without COM registration. Test server-to-client and client-to-server success, duplicate Replace/Don't copy/Cancel, DeskFlow Cancel during receipt and during Explorer reads, mixed DPI, reconnect, and input/clipboard responsiveness.

Record exact results in the Phase 4 handoff and update Plan 004 done criteria only for verified rows.

**Verify**: clean-machine launch succeeds on both PCs; automated suite passes; manual matrix has no unexplained result.

## Test plan

Test QueryInterface, refcounts, async-mode transitions, success/error HRESULT mapping, user cancellation precedence, fallback mode, repeated publishing, process shutdown, and packaged artifact discovery. Use a manual Explorer test only after isolated COM tests pass.

## Done criteria

- [ ] One documented reproducible native build command exists.
- [ ] No administrator COM registration is required.
- [ ] Explorer can query both required interfaces.
- [ ] EndOperation result controls terminal state when negotiated.
- [ ] Fallback remains functional when async mode is declined.
- [ ] Both-computer matrix passes and is recorded.

## STOP conditions

Stop if the compiler/SDK is absent, the bridge requires global registration, Python callback lifetime is ambiguous, QueryInterface or reference counting is unstable, Explorer does not query the capability during clipboard paste, packaging changes the process architecture, or a crash occurs. Write a handback with HRESULTs, event order, toolchain output, and the smallest reproduction.

## Maintenance notes

This bridge also provides the prerequisite for issue #1's responsive Explorer async extraction. Do not expand it into a general native transfer engine.
