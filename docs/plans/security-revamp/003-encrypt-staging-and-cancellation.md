# Plan 003: Encrypt staging and rebuild cancellation

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001, 002
- **Planned at**: `8b329d8`, 2026-07-13
- **Completed at**: `f995183`, 2026-07-13

## Current state and intent

`app/file_transfer/staging.py` is plaintext but supports direct seeks. Receiver cancellation clears staging while queued chunks can recreate it. Implement AES-GCM record staging with requested-record reads, encrypted verified cache, explicit cleanup, and one idempotent cancel request/ack with terminal tombstones.

## Steps and gates

1. Add failing staging tests for ciphertext-at-rest, cross-record random reads, growing reads, tamper detection, finalize without plaintext cache, cleanup, and read cost independent of prefix size. Implement the record store.
2. Add failing receiver tests proving no condition lock is held during decrypt/read and abandoned ciphertext is cleaned at startup.
3. Add failing protocol tests for local/remote cancellation, duplicate request/ack, late chunk/completion frames, cancellation during verification, and immediate next transfer. Implement the state transition and bounded tombstones.
4. Add a deterministic staging benchmark and run focused transfer, full suite, and compile gates.

## Done criteria

- DeskFlow-owned transfer files contain no plaintext payload.
- Range work scales with intersecting records.
- Both peers converge on cancelled state without message echo.
- Late frames cannot recreate files or poison the next job.
