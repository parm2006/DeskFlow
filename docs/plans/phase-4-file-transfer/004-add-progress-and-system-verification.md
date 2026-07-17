# Plan 004: Add non-blocking progress and verify the system

> UI must never steal focus from the paste target or input overlay.
>
> **Drift check**: `git diff d352936 -- app/gui.py app/file_transfer tests README.md features.md plan.md`

## Status

- **Effort**: M
- **Risk**: MED
- **Depends on**: 003
- **Planned at**: `d352936`, 2026-07-11

## Why this matters

Background transfer needs visible, trustworthy state without extra interaction. Manual two-machine evidence is required before claiming normal copy/paste behavior.

## Current state

- `app/gui.py` exposes one main CustomTkinter window and a transparent input overlay.
- No transfer progress, queue, cancellation, or bandwidth profile UI exists.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Full tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

In scope: non-focus-stealing current-transfer progress toast, cancel action, balanced-profile display/settings, docs, automated state tests, and two-machine checklist. User-facing queue support and queue counts are deferred to GitHub issue #1.

Out of scope: pause/resume UI unless engine support is already complete, transfer history database, notifications service, and arbitrary app paste support.

## Steps

1. Add a compact bottom-right toast driven only by transfer-engine events: preparing, compressing when applicable, transferring, verifying, completed, failed, and cancelled. It must not follow the cursor or steal focus. Do not display a queue count.
2. Show bytes, percent, throughput, and ETA when measurable. Explain that known compressed formats are sent raw; do not expose internal archive files because decompression is automatic.
3. Add cancellation and balanced network mode. Cancellation stops the current job and cleans its partial files. Do not advertise user-facing queued jobs.
4. Document security boundaries, Explorer/Desktop scope, source-file availability requirement, automatic decompression, staging location, limits, and failure recovery.
5. Run two-computer tests in both directions: small/large compressible and precompressed files, multi-file and directories, multiple queued pastes, text/screenshots during transfers, cancellation, disconnect, low disk, filename attacks, and control latency under load.

## Done criteria

- [ ] Full tests and compile checks pass.
- [ ] Toast never steals focus in manual tests.
- [ ] Mouse/keyboard and ordinary clipboard remain responsive during saturated transfer.
- [ ] Balanced throttling responds to measured latency thresholds.
- [ ] Completed files match source SHA-256.
- [ ] Security/failure matrix passes on two machines.

## STOP conditions

Stop if GUI event delivery blocks transfer or input threads, progress requires polling unbounded shared state, or measured latency protection cannot keep input responsive on the test network.

## Maintenance notes

Keep UI as an observer of transfer state. Never make transfer correctness depend on the toast being open.
