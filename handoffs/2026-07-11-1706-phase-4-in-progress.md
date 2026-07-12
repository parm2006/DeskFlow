# phase-4-in-progress | thread: deskflow-hardening | status: active | The clipboard fix is confirmed working under load; Phase 4 file transfer Plan 001 is implemented but failing manual tests due to COM/OLE initialize issues.

## What changed
- **Phase 4 Planning**: Created `docs/plans/phase-4-file-transfer/` containing the README and plans 001 through 004 for the secure queued transfer engine.
- **Plan 001 Implementation (Uncommitted)**:
  - Added `app/windows_virtual_files.py` to support OLE virtual files using `IDataObject`, `FileGroupDescriptorW`, and `FileContents`.
  - Added `tests/test_windows_virtual_files.py` and `tests/manual_virtual_file_paste.py`.
  - Addressed COM/OLE `CoInitialize` and `OleInitialize` teardown errors in the tests.
  - Replaced `pythoncom.com_error` with `COMException` in `app/windows_virtual_files.py` to correctly return HRESULTs to Windows without crashing PyWin32.
- **Plan 002 Implementation (Uncommitted)**:
  - Created `app/file_transfer/models.py` (Manifest, FileItem, Chunk, Job).
  - Created `app/file_transfer/validation.py` (path, size, and symlink validation).
  - Created `app/file_transfer/transport.py` (authenticated TLS file lane on `port + 2` with single-session tokens).
  - Created `task.md` for Plan 002.

## What works (verified)
- **Clipboard Latest-Wins Fix**: The two-machine rapid-screenshot burst test succeeded without dropping the connection. The clipboard fix on the `fix/clipboard-latest-wins` branch is officially fully verified!

## Broken or open
- **Plan 001 Manual Test is Crashing**: Running `.\venv\Scripts\python.exe -m tests.manual_virtual_file_paste` still throws a bizarre `AttributeError: module 'pythoncom' has no attribute 'OleUninitialize'` even though `CoUninitialize()` is the active code on disk. This is preventing Plan 001 from being manually verified.
- **Changes are uncommitted**: The previous commit for Plan 001 was rolled back via soft reset per user request. All Phase 4 code (`app/windows_virtual_files.py`, `docs/plans`, `tests/manual_virtual_file_paste.py`, and the new `app/file_transfer/` files) is currently uncommitted in the working tree.

## Key facts
- Branch: `fix/clipboard-latest-wins` (up to date with remote).
- The `[WinError 10054]` issue is considered resolved for clipboard bursts.

## Resume by
1. Investigate why `tests/manual_virtual_file_paste.py` is still raising an error about `OleUninitialize` when the file has been modified to use `CoUninitialize`. (It may require a clean terminal session or pyc cache clear).
2. Successfully execute the manual test (`.\venv\Scripts\python.exe -m tests.manual_virtual_file_paste`) and paste the test files into Explorer.
3. Once Plan 001 is verified, commit the Plan 001 files.
4. Continue with Plan 002's remaining steps (engine, hashing, and compression) in `task.md`.
