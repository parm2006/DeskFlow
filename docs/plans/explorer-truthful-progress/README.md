# Explorer-truthful progress and toast placement

Make both DeskFlow toasts remain visible until Explorer finishes the paste, measure progress at the actual `IStream.Read` boundary, use the Shell's async lifecycle as the authoritative result, and keep each toast inside its owning monitor. The approved design is [`../../superpowers/specs/2026-07-12-explorer-truthful-progress-design.md`](../../superpowers/specs/2026-07-12-explorer-truthful-progress-design.md). Planned at revision `afcdbba` on 2026-07-12.

Execute in this order. Read each plan fully, honor STOP conditions, and update its status after verification.

## Execution order and status

| Plan | Title | Effort | Depends on | Status |
|---|---|---:|---|---|
| [001](001-fix-toast-monitor-placement.md) | Keep every toast inside its owning monitor | S | - | DONE |
| [002](002-report-explorer-consumed-progress.md) | Mirror measured Explorer-consumed progress | L | 001 | IN PROGRESS |
| [003](003-add-async-shell-lifecycle.md) | Use Explorer's async lifecycle as the authoritative result | L | 002 | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED | SUPERSEDED

## Dependency notes

- **001 -> 002**: establish reliable UI visibility before changing the status model.
- **002 -> 003**: the native lifecycle supplies final outcome; unique `IStream.Read` coverage remains the progress source.

## Reconciliation log

- **2026-07-12**: Plan 002 automated checkpoint completed with Explorer-only user-facing progress, unique range accounting, nonblocking/rate-limited peer mirroring, and 114 passing tests. Two-computer conflict-dialog and large-file verification pending.
- **2026-07-12**: Plan 001 accepted after both toasts stayed fully visible, cancelled correctly, and the serialized TLS path remained connected during input. Plan 002 started.
- **2026-07-12**: First Plan 001 manual check exposed an untyped 64-bit `SetWindowPos` call (`WinError 1400`) that also prevented hide scheduling. Added typed WinAPI boundaries, placement-failure isolation, and serialized ordinary TLS writes after a concurrent Ctrl+click produced `BAD_RECORD_MAC`. Manual recheck remains.
- **2026-07-12**: Split the approved design into a safe DPI fix, Python-measurable Explorer progress, and an isolated native COM lifecycle bridge. Destination-toast hiding remains deferred to issue #2.

## Considered and rejected

- Keep network-staging percent as the only bar: truthful for transport but misleading for the user's paste operation.
- Poll Explorer's progress window: localized, focus-sensitive, and not an operation contract.
- Move all file transfer code native: unnecessary and expands the security surface.

## Deferred

- Hide destination toast while Explorer shows native progress: GitHub issue #2.
- User-facing multi-destination queue: GitHub issue #1; the native async bridge may satisfy its prerequisite but does not implement the feature.
