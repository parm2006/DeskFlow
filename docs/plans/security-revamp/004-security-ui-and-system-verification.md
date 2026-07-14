# Plan 004: Finish security UI and system verification

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001, 002, 003
- **Planned at**: `8b329d8`, 2026-07-13

## Current state and intent

`app/gui.py` uses a fixed non-copyable status label. Integrate explicit first pairing, inline re-pair and recovery, adaptive selectable error details, and the complete security verification matrix without adding daemon/background behavior.

## Steps and gates

1. Add presenter/view-model tests for safe pairing, timeout, authentication, identity recovery, re-pair, and cancellation messages; implement a typed UI model.
2. Replace fixed status rendering with a resizable copyable inline panel and inline actions. Marshal every network callback to Tk's thread.
3. Run all automated tests, compile checks, secret/path scans, identity migration checks, staging benchmarks, and loopback transport abuse tests.
4. Execute and record the two-computer matrix: both directions, first/saved/changed pairing, re-pair, 100 MB throughput, latency during transfer, cancel on either peer, immediate next transfer, reconnect, and GUI resize/copy.

## Done criteria

- Errors and recovery stay in the main window and are selectable/copyable.
- Every security requirement has direct automated or recorded manual evidence.
- Daemon/background files remain unchanged.
- Full suite and compile check pass with a clean tracked worktree.

