# Plan 001: Validate native Windows virtual-file paste

> Follow test-first where automation is possible. Stop and write a handback if pywin32 cannot keep an OLE data object alive independently after the global clipboard changes.
>
> **Drift check**: `git -c safe.directory='<REPOSITORY_ROOT>' diff d352936 -- app tests requirements.txt`

## Status

- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Planned at**: `d352936`, 2026-07-11

## Why this matters

The requested UX depends on Explorer retaining a paste operation after the user copies something else. Prove the Windows OLE boundary before building the transfer engine.

## Current state

- `app/clipboard_handler.py` uses basic Win32 clipboard APIs for text, DIB, HTML, and RTF.
- `app/input_handler.py:142-146` exposes key press/release callbacks.
- No OLE `IDataObject`, `FileGroupDescriptorW`, or `FileContents` implementation exists.
- Dependencies must be added to `requirements.txt` and installed only through `run.bat` per `.agents/AGENTS.md`.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

In scope: `app/windows_virtual_files.py`, `tests/test_windows_virtual_files.py`, and `requirements.txt` only if the existing pywin32 surface is insufficient.

Out of scope: networking, production clipboard routing, GUI, file security, and remote transfer.

## Steps

1. Write pure tests for descriptor names, sizes, timestamps, stream indexing, Unicode filenames, multi-file selection, and directory descriptors.
2. Implement the smallest OLE data object that exposes `FileGroupDescriptorW` and indexed `FileContents` streams backed by deterministic local test bytes.
3. Manually paste into Explorer and Desktop, then change the global clipboard while a throttled stream is still being consumed. Confirm the paste completes and the newer clipboard remains intact.
4. Record supported destinations and pywin32/COM limitations in this plan.

## Done criteria

- [x] Automated descriptor/stream tests pass (9 focused tests; 18 repository tests total).
- [x] Explorer and Desktop paste multiple test files correctly.
- [x] Changing the clipboard after paste begins does not cancel or corrupt it; the newer text remains pasteable.
- [x] No production network or clipboard path is changed.

## Verification record

- **2026-07-11 automated**: `.\venv\Scripts\python.exe -m unittest discover -s tests -v` passed 18/18 tests; `.\venv\Scripts\python.exe -m compileall -q app tests` exited 0.
- **2026-07-11 manual**: two virtual text files pasted correctly into both Explorer and Desktop. Copying new text after `Ctrl+V` did not interrupt or corrupt the file paste, and the new text subsequently pasted correctly.
- **COM limitation**: the publisher must run on an OLE-initialized thread and keep the Python data object alive while Windows consumes its streams. Production network and clipboard routing remain unchanged in this plan.

## STOP conditions

Stop if Explorer requires clipboard ownership for the entire transfer, pywin32 cannot provide asynchronous streams safely, or COM work must move into a native extension. Write a handback comparing a minimal native helper versus the staging fallback.

## Maintenance notes

Keep COM lifetime and apartment/thread rules explicit. Never run blocking network reads on the GUI thread.
