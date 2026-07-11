# reliability-cleanup | thread: deskflow-hardening | status: active | Latest-wins clipboard scheduling is implemented and automated tests pass; two-machine validation remains.

## What changed
- `app/latest_wins_sender.py` — added a one-active/one-replaceable-pending worker with snapshot ownership, bounded stop, idle waiting, and exception recovery.
- `app/clipboard_handler.py` — separated raw Windows clipboard capture from zlib/Base64 wire encoding so polling no longer compresses or sends inline.
- `app/client.py` and `app/server.py` — route outbound clipboard snapshots through per-peer latest-wins senders without mutating callback dictionaries.
- `tests/test_latest_wins_sender.py` and `tests/test_clipboard_scheduling.py` — added scheduler concurrency/lifecycle tests plus text/image/HTML/RTF compatibility and peer-routing tests.
- `docs/superpowers/specs/2026-07-11-clipboard-reliability-phase-1-design.md` — narrowed the stale protocol redesign to the approved backpressure-only scope.
- `docs/plans/clipboard-latest-wins.md` — recorded the implementation and verification plan.

## What works (verified)
- All 9 automated tests pass — `.\venv\Scripts\python.exe -m unittest discover -s tests -v` → `Ran 9 tests ... OK`.
- Python sources compile — `.\venv\Scripts\python.exe -m compileall -q app tests` → exit 0.
- Diff formatting is clean — `git -c safe.directory='C:/Users/parth/Projects/DeskFlow' diff --check` → no output.
- A/B/C/D scheduling sends A then D, payloads are snapshotted, pending work is dropped on stop, and a send exception does not kill the worker — verified by `tests/test_latest_wins_sender.py`.
- Existing text/image/HTML/RTF keys and codecs remain compatible — verified by encode/decode assertions in `tests/test_clipboard_scheduling.py`.

## Broken or open
- **Two-machine behavior is not yet verified** — automated tests cannot prove Windows clipboard and network behavior under real screenshot bursts. Next: run both peers, capture logs on both, take rapid screenshots, and paste the final image repeatedly.
- **The `[WinError 10054]` cause remains unproven** — this slice bounds outbound work but does not establish that backpressure caused the earlier reset. Next: compare both peer logs during the manual reproduction.
- **Changes are uncommitted** — HEAD remains `8799e09`; source, tests, plan, spec revision, and handoffs are in the working tree. Next: commit only after manual acceptance or explicit user direction.

## Key facts
- Branch: fix/clipboard-latest-wins
- Commit: 8799e09
- Parent handoff: handoffs/2026-07-11-1030-reliability-cleanup.md
- Decisions not yet captured elsewhere: retain the existing rich clipboard wire format; treat latest-wins as backpressure rather than delivery confirmation; defer protocol and security hardening.

## Resume by
1. Run `run.bat` on both Windows computers from this branch/build and connect them normally.
2. Copy ordinary text, one image, HTML, and RTF in both directions, then take a burst of screenshots and verify the final screenshot remains pasteable.
3. Save logs from both peers if a disconnect or paste failure occurs; do not infer the cause from one side alone.
4. If the manual check passes, run the automated suite once more and choose whether to commit, merge, or keep the branch.

Open question for the user: Did the two-machine rapid-screenshot test preserve paste availability and the connection?
