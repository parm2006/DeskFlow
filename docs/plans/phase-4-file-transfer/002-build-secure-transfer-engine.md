# Plan 002: Build the secure queued transfer engine

> Follow every verification gate. Do not integrate keyboard interception or Explorer paste in this plan.
>
> **Drift check**: `git -c safe.directory='C:/Users/parth/Projects/DeskFlow' diff d352936 -- app/network.py app/crypto.py app/file_transfer tests requirements.txt`

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001
- **Planned at**: `d352936`, 2026-07-11

## Why this matters

File jobs need durable identity, bounded resource use, integrity verification, and transport isolation. Ordinary clipboard latest-wins behavior must never govern initiated file jobs.

## Current state

- `app/network.py` offers TLS sockets and JSON length-prefixed messages but the client disables certificate verification.
- `app/server.py` uses ports `port` and `port + 1`; file bytes need their own authenticated lane.
- `app/latest_wins_sender.py` is intentionally unsuitable for FIFO file jobs.

## Commands

| Purpose | Command | Expected |
|---|---|---|
| Focused | `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_file_transfer*.py" -v` | all pass |
| Full | `.\venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass |
| Syntax | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0 |

## Scope

In scope: new modules under `app/file_transfer/`, focused additions to `app/network.py`, `app/crypto.py`, client/server lifecycle wiring, and `tests/test_file_transfer*.py`.

Out of scope: OLE paste, key interception, final GUI styling, Internet relay, source deletion, and auto-execution.

## Steps

1. Define immutable manifest/job/chunk models. Manifest includes random job ID, safe relative names, type, size, timestamps, file count, total size, and local-only source paths. Never send absolute source paths.
2. Implement validation: reject traversal, absolute/drive paths, alternate data streams, reserved Windows names, unsafe depth/count/path lengths, reparse points, over-limit sizes, and insufficient disk space.
3. Add an authenticated file lane (`port + 2` or negotiated port) with random single-session tokens and certificate-fingerprint pairing. Do not rely on `CERT_NONE` for trusted identity.
4. Implement FIFO jobs with one active chunk writer initially. Jobs persist independently from clipboard changes and support cancellation, failure, and bounded retry.
5. Stream to unpredictable `.partial` files inside a controlled DeskFlow staging directory. Incrementally hash original bytes with SHA-256; verify before atomic rename. Never overwrite or execute files.
6. Implement adaptive compression: skip known compressed formats and files below 1 MiB; sample 256 KiB; enable fast zlib only at ≥12% savings; compress independent 1 MiB chunks; bound decompressed output.
7. Implement balanced rate control from control RTT: start near 50% spare throughput; reduce at +15 ms, aggressively throttle at +40 ms, pause around +100 ms/repeated stalls, and recover gradually. Control/clipboard traffic always has priority.
8. Add structured status events without logging file contents or full private paths.

## Test plan

Cover FIFO ordering, multiple files/folders, mutation/deletion after manifest, truncated chunks, hash mismatch, retry, cancel, disk exhaustion, collision handling, malicious paths, symlinks/reparse points, compression decisions, decompression bounds, token misuse, unauthenticated peers, latency throttling, and cleanup of partial files.

## Done criteria

- [x] Focused and full tests pass (37 focused; 55 repository tests).
- [x] Malicious paths never escape staging.
- [x] Every completed file passes size and SHA-256 verification.
- [x] Control latency tests prove file traffic throttles without blocking control/clipboard queues.
- [x] No transferred file is automatically opened or executed.

## Verification record

- **2026-07-11**: `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_file_transfer*.py" -v` passed 37/37.
- **2026-07-11**: `.\venv\Scripts\python.exe -m unittest discover -s tests -v` passed 55/55.
- **2026-07-11**: `.\venv\Scripts\python.exe -m compileall -q app tests` exited 0.
- A loopback TLS integration test transfers bytes through the authenticated file lane, then verifies size and SHA-256 before no-overwrite publication.
- The file lane is bound to the live authenticated control connection's certificate fingerprint and a random single-use token delivered over that control connection.

## STOP conditions

Stop if a third socket cannot coexist with current lifecycle safely, fingerprint pairing requires an unresolved UX decision, or reliable cancellation requires changing the virtual-file contract proven in 001.

## Maintenance notes

Treat compression as a transport optimization, not an archive format. Preserve original bytes and filenames exactly after successful verification.
