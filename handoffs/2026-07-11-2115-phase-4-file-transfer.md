# phase-4-file-transfer | thread: deskflow-hardening | status: active | Plan 002 secure queued transfer engine is verified; Plan 003 paste integration is next.

## What changed
- `app/file_transfer/` — added immutable manifests, validation, source snapshots, FIFO jobs, compression, rate control, bounded framing, authenticated TLS transport, sender/receiver, and verified staging.
- `app/network.py` — exposed the live TLS peer certificate fingerprint for file-lane session binding.
- `app/client.py` and `app/server.py` — added the dedicated `port + 2` file lane and single-use token offer over the authenticated control lane.
- `tests/test_file_transfer_*.py` — added 37 focused security, integrity, scheduling, compression, latency, lifecycle, and end-to-end tests.

## What works (verified)
- Focused Plan 002 suite — `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_file_transfer*.py" -v` → 37/37 passed.
- Full repository suite — `.\venv\Scripts\python.exe -m unittest discover -s tests -v` → 55/55 passed.
- Compilation — `.\venv\Scripts\python.exe -m compileall -q app tests` → exit 0.
- End-to-end TLS transfer — loopback test authenticated with the control certificate fingerprint and a single-use token, transferred bounded chunks, verified SHA-256, and published without overwrite.

## Broken or open
- **Paste workflow is not integrated** — the engine exists, but Ctrl+V does not yet snapshot a file clipboard into a queued job or expose its receiver through the virtual-file provider. Next: execute Plan 003.
- **Changes remain uncommitted** — Phase 4 Plans 001 and 002 share the working tree with their documentation and handoffs.

## Key facts
- Branch: `fix/clipboard-latest-wins`
- Commit: `d352936` plus uncommitted Phase 4 work
- Parent handoff: `2026-07-11-1715-phase-4-file-transfer.md`
- Decisions not yet captured elsewhere: the file lane trusts only the certificate already observed on the authenticated control connection; it does not introduce a second fingerprint UI.

## Resume by
1. Execute `docs/plans/phase-4-file-transfer/003-integrate-manifest-on-paste.md` test-first.
2. Detect a remote Ctrl+V while the source clipboard contains files, snapshot the manifest, and enqueue it independently from later clipboard changes.
3. Back the destination OLE virtual files with receiver streams without blocking control or clipboard activity.

Open question for the user: none
