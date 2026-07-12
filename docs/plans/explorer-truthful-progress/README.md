# Explorer-truthful progress and toast placement

Make both DeskFlow toasts remain visible until Explorer finishes the paste, measure progress at the actual `IStream.Read` boundary, use the Shell's async lifecycle as the authoritative result, and keep each toast inside its owning monitor. The approved design is [`../../superpowers/specs/2026-07-12-explorer-truthful-progress-design.md`](../../superpowers/specs/2026-07-12-explorer-truthful-progress-design.md). Planned at revision `afcdbba` on 2026-07-12.

Execute in this order. Read each plan fully, honor STOP conditions, and update its status after verification.

## Execution order and status

| Plan | Title | Effort | Depends on | Status |
|---|---|---:|---|---|
| [001](001-fix-toast-monitor-placement.md) | Keep every toast inside its owning monitor | S | - | IN PROGRESS - automated gates pass; two-computer DPI check pending |
| [002](002-report-explorer-consumed-progress.md) | Mirror measured Explorer-consumed progress | L | 001 | TODO |
| [003](003-add-async-shell-lifecycle.md) | Use Explorer's async lifecycle as the authoritative result | L | 002 | TODO |

Status values: TODO | IN PROGRESS | DONE | BLOCKED | SUPERSEDED

## Dependency notes

- **001 -> 002**: establish reliable UI visibility before changing the status model.
- **002 -> 003**: the native lifecycle supplies final outcome; unique `IStream.Read` coverage remains the progress source.

## Reconciliation log

- **2026-07-12**: Split the approved design into a safe DPI fix, Python-measurable Explorer progress, and an isolated native COM lifecycle bridge. Destination-toast hiding remains deferred to issue #2.

## Considered and rejected

- Keep network-staging percent as the only bar: truthful for transport but misleading for the user's paste operation.
- Poll Explorer's progress window: localized, focus-sensitive, and not an operation contract.
- Move all file transfer code native: unnecessary and expands the security surface.

## Deferred

- Hide destination toast while Explorer shows native progress: GitHub issue #2.
- User-facing multi-destination queue: GitHub issue #1; the native async bridge may satisfy its prerequisite but does not implement the feature.
