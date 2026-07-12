# phase-4-file-transfer | thread: deskflow-hardening | status: active | Plan 003 is verified with one accepted Explorer async-UI limitation; Plan 004 is next.

## What changed
- `app/file_transfer/executor.py` — enforces one active sender and strict FIFO transfer order.
- `app/file_transfer/staging.py` — isolates completed files by job ID so repeated filenames cannot collide.
- `app/file_transfer/receiver.py` and `transport.py` — wake blocked readers on failure and prevent one job callback from killing the shared lane.
- `app/input_geometry.py` and `app/gui.py` — keep the server taskbar visible and avoid immediate screen-edge bounce.
- GitHub issue #1 — records the deferred native `IDataObjectAsyncCapability` helper for responsive multi-destination Explorer pastes.

## What works (verified)
- Automated suite — `.\venv\Scripts\python.exe -m unittest discover -s tests -v` → 83/83 passed before the documentation-only update.
- Compilation — `.\venv\Scripts\python.exe -m compileall -q app tests` → exit 0.
- Both directions — user verified server→client and client→server file paste.
- Coverage — user verified small/100 MB files, multiple files, folders, Desktop/Explorer, screenshots/text during transfer, disconnect/reconnect, repeated filenames, and cut-as-copy.

## Broken or open
- **Explorer folder UI blocks during active virtual stream** — pywin32 data object lacks `IDataObjectAsyncCapability`. Selecting all desired files in one operation is the supported current workflow. Next: defer to https://github.com/parm2006/DeskFlow/issues/1.
- **Plan 004 remains** — progress toast, real DeskFlow cancellation, live rate-controller wiring, documentation, and final security/failure matrix.

## Key facts
- Branch: `fix/clipboard-latest-wins`
- Commit: `98038ce` plus this uncommitted documentation update
- Parent handoff: `2026-07-11-2115-phase-4-file-transfer.md`
- Decisions not yet captured elsewhere: multi-destination queue UI does not block Plan 3 because multi-selection covers the common workflow.

## Resume by
1. Execute `docs/plans/phase-4-file-transfer/004-add-progress-and-system-verification.md` test-first.
2. Add transfer status events and a non-focus-stealing progress/queue toast.
3. Wire cancellation and balanced rate control into live jobs, then run the final two-machine matrix.

Open question for the user: none
