# Plan 001: Keep every transfer toast inside its owning monitor

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If a STOP condition occurs, write a handback instead of improvising. When done, update this plan's status in `README.md`.
>
> **Drift check (run first)**: `git diff afcdbba -- app/input_geometry.py app/file_transfer/toast.py tests/test_input_geometry.py tests/test_file_transfer_toast.py`
> If these files changed, compare the current-state notes with live code. Stop on a semantic mismatch.

## Status

- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Planned at**: revision `afcdbba`, 2026-07-12

## Why this matters

The client toast is partly beyond the right edge on a scaled laptop display. The current calculation mixes the primary monitor's Win32 physical rectangle with Tk geometry units. Cancellation is unusable when the button is off-screen.

## Current state

- `app/input_geometry.py:20` scales the global work area using ratios derived from global screen metrics.
- `app/file_transfer/toast.py:70-94` positions the toast before anchoring the calculation to the toast's native window or monitor.
- `tests/test_input_geometry.py` tests one ratio calculation but does not test per-window monitor selection or clamping.
- Match the small pure geometry helpers in `app/input_geometry.py`; keep Win32 calls outside calculation functions so unit tests remain platform-independent.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused tests | `.\venv\Scripts\python.exe -m unittest tests.test_input_geometry tests.test_file_transfer_toast -v` | all pass |
| Full suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

**In scope**: `app/input_geometry.py`, `app/file_transfer/toast.py`, `tests/test_input_geometry.py`, `tests/test_file_transfer_toast.py`.

**Out of scope**: transfer phases, COM streams, networking, overlay capture behavior, and issue #2's optional destination-toast hiding.

## Steps

### Step 1: Specify monitor-local clamping

Add failing pure tests for 100%, 125%, 150%, and 200% scaling. Cover a primary monitor, a negative-coordinate monitor, taskbars on different edges, and a proposed rectangle beyond every work-area edge. The output rectangle must fit wholly inside the supplied work area.

**Verify**: focused tests fail because the monitor-local API does not exist.

### Step 2: Resolve placement from the toast HWND

After `CTkToplevel` creates its native window, obtain the correct top-level `HWND`. Use `MonitorFromWindow(..., MONITOR_DEFAULTTONEAREST)`, `GetMonitorInfoW.rcWork`, and `GetDpiForWindow`. Convert once into the coordinate system Tk expects, clamp all four edges, then call `geometry`. Do not use the root window's monitor, primary-screen metrics, or a global ratio.

Keep the pure rectangle conversion separate from ctypes structures and calls. Log the monitor work area, DPI, requested rectangle, and final rectangle at debug level without file or user data.

**Verify**: focused tests pass.

### Step 3: Preserve non-activation behavior

Confirm placement changes neither call `focus_*` nor add a grab. Keep `overrideredirect` and topmost behavior. Add a structural test or narrow mock test that positioning uses the toast window handle rather than the root handle.

**Verify**: full suite and syntax commands pass.

## Test plan

Follow the table-driven style in `tests/test_input_geometry.py`. Tests must prove full containment, not merely compare one hand-calculated right edge.

## Done criteria

- [ ] Four DPI scale cases and negative coordinates pass.
- [ ] Positioning selects the toast's monitor and work area.
- [ ] No focus or grab behavior is added.
- [ ] Full tests and compile check pass.
- [ ] Only in-scope files changed.

## STOP conditions

Stop if Tk reports window positions and sizes in different coordinate systems on the same machine, the actual top-level HWND cannot be obtained reliably, or placement requires changing process DPI awareness after any HWND exists. Record observed values and the failing display configuration.

## Maintenance notes

Test placement on both computers before marking the plan done. Optional destination-toast hiding remains issue #2.
