# Phase 4: Background file copy and paste

Implement Windows Explorer/Desktop file copy-paste between paired DeskFlow computers. A remote `Ctrl+V` snapshots the source file clipboard into an independent FIFO transfer job; subsequent text, screenshot, mouse, keyboard, and file-copy activity continues normally. Planned at `d352936` on 2026-07-11.

Execute in order. Read each plan fully, honor STOP conditions, and update its row when completed.

## Execution order and status

| Plan | Title | Effort | Depends on | Status |
|---|---|---:|---|---|
| [001](001-validate-windows-virtual-file-paste.md) | Validate native virtual-file paste | M | — | DONE |
| [002](002-build-secure-transfer-engine.md) | Build secure queued transfer engine | L | 001 | DONE |
| [003](003-integrate-manifest-on-paste.md) | Integrate manifest-on-paste workflow | L | 001, 002 | DONE |
| [004](004-add-progress-and-system-verification.md) | Add progress UI and system verification | M | 003 | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED | SUPERSEDED

## Dependency notes

- **001 → 002/003**: prove pywin32 can supply virtual files to Explorer without retaining the global clipboard before committing to the full architecture.
- **002 → 003**: paste integration consumes the authenticated, bounded, resumable job engine.
- **003 → 004**: progress UI observes real transfer state instead of inventing a parallel state model.

## Compression and network decisions

- A file-size threshold does not decide compression; files stream in bounded chunks regardless of total size.
- Known compressed formats are never recompressed.
- Files below 1 MiB are sent raw.
- Other candidates sample 256 KiB; use fast zlib only when the sample is at least 12% smaller.
- Use independent 1 MiB chunks so retries and memory remain bounded; decompression is automatic and invisible.
- Balanced network mode starts near 50% of measured spare throughput, reduces file traffic when control latency rises 15 ms above baseline, throttles aggressively at +40 ms, and temporarily pauses file chunks around +100 ms or repeated stalls.
- Mouse/keyboard, control, and ordinary clipboard traffic always outrank file chunks.

## Reconciliation log

- **2026-07-11**: Initial Phase 4 plans created from the approved manifest-on-paste, FIFO job, virtual-file, security, adaptive-compression, and balanced-network design.
- **2026-07-11**: Plan 001 verified with 18/18 automated tests plus successful Explorer/Desktop paste and clipboard-replacement checks. Plan 002 began only as an unverified prototype and still requires its planned test-first security review.
- **2026-07-11**: Replaced the Plan 002 prototype with a test-first engine. Verified FIFO jobs, bounded authenticated TLS framing, session-bound certificate identity, strict paths, source mutation detection, adaptive compression, latency throttling, partial-file cleanup, and end-to-end SHA-256 publication with 37 focused and 55 total tests.
- **2026-07-12**: Plan 003 verified in both directions with small/large files, multi-file selections, folders, Desktop/Explorer destinations, screenshots/text during transfer, reconnect, and cut-as-copy. Strict FIFO sending is automated. Multi-destination pastes during one active Explorer operation are deferred in [GitHub issue #1](https://github.com/parm2006/DeskFlow/issues/1) because Explorer requires `IDataObjectAsyncCapability` to keep its folder UI interactive during lengthy virtual-file extraction.

## Considered and rejected

- Download-then-replace-clipboard: loses or races with screenshots/text copied during transfer.
- Guess active Explorer destination and write directly: fragile outside a narrow set of Explorer windows.
- Compress every large file: wastes CPU on already-compressed media, archives, Office files, PDFs, and installers.
- Treat files as latest-wins clipboard content: violates the requirement that every initiated paste completes independently.

## Deferred

- Cross-platform file paste, Internet relay, cut/delete semantics, arbitrary application upload fields, and automatic execution.
- Multiple destination folders while a prior Explorer virtual-file paste is still active; see [GitHub issue #1](https://github.com/parm2006/DeskFlow/issues/1).
