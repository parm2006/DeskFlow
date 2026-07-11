# reliability-cleanup | thread: deskflow-hardening | status: active | Latest-wins clipboard scheduling has a passing focused test but is not integrated into either peer.

## What changed
- `tests/test_latest_wins_sender.py:1` — added a focused regression test that blocks active send A, submits B, C, and D, then asserts that only A and D are delivered.
- `app/latest_wins_sender.py:1` — added `LatestWinsSender`, a daemon-worker scheduler with one active send and one replaceable pending payload snapshot.

## What works (verified)
- The regression test first failed because the scheduler module did not exist — `python -m unittest tests.test_latest_wins_sender -v` → `ModuleNotFoundError: No module named 'app.latest_wins_sender'`.
- Active A completes and only latest pending D follows — `python -m unittest tests.test_latest_wins_sender -v` → 1 test ran, `OK`.

## Broken or open
- **The scheduler is not integrated** — client and server still send synchronously and mutate the observed payload. Next: add compatibility tests, then route both through `LatestWinsSender` while preserving text, image, HTML, and RTF.
- **The design spec remains too broad** — it still specifies protocol changes outside the approved scope. Next: narrow it to one active plus one replaceable pending snapshot and the existing wire schema.
- **Workspace patching is intermittent** — `apply_patch` fails because `codex-windows-sandbox-setup.exe` is missing. Next: restart Codex and verify a small patch.
- **Lifecycle behavior is unwired** — sender stop and reconnect ownership need integration and tests.

## Key facts
- Branch: fix/clipboard-latest-wins
- Commit: 8799e09
- Parent handoff: handoffs/2026-07-11-1030-reliability-cleanup.md
- Decisions not yet captured elsewhere: preserve the existing schema; finish A; replace B and C with D; never interrupt an active TCP frame; copy payload dictionaries rather than mutating them.

## Resume by
1. Restart Codex and verify a harmless `apply_patch` create/remove cycle.
2. Rerun `python -m unittest tests.test_latest_wins_sender -v`.
3. Continue TDD for payload compatibility, peer integration, and lifecycle behavior.
4. Run the complete available test suite and narrow the design spec before committing.

Open question for the user: none
