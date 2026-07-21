# Portable ordered clipboard sync

This effort implements the approved [portable clipboard sync design](../../superpowers/specs/2026-07-21-portable-clipboard-sync-design.md) from revision `15a8092efe7ea21cc865f643be046ce546207bad`. It first creates a bounded versioned snapshot model, then adds a Windows adapter that preserves source format order, and finally switches the live client/server path and runs the Google Docs/Word acceptance matrix.

Execute in the order below. Each executor must read its plan fully, work test-first, honor every STOP condition, and update its status row when done.

## Execution order and status

| Plan | Title | Effort | Depends on | Status |
|---|---|---|---|---|
| [001](001-build-bounded-ordered-snapshot.md) | Build the bounded ordered clipboard snapshot | M | — | DONE |
| [002](002-add-windows-ordered-clipboard-adapter.md) | Add ordered Windows capture and publication | L | 001 | DONE |
| [003](003-integrate-and-validate-portable-sync.md) | Integrate v2 sync and validate Docs/Word | L | 001, 002 | IN PROGRESS — physical test pending |

Status values: TODO, IN PROGRESS, DONE, BLOCKED, or SUPERSEDED.

## Dependency notes

- **001 → 002**: the Windows layer must target one reviewed snapshot model and
  one source of size limits.
- **001 + 002 → 003**: live routing should switch only after codec validation
  and native format ordering are independently covered.

## Reconciliation log

- **2026-07-21**: Initial plans written. Next: 001.

## Considered and rejected

- Mirroring every registered format: expands the attack surface and can move
  application-private or path-bearing data.
- Remote OLE/`IDataObject` proxy: high lifetime, threading, and trust complexity
  without evidence that the portable formats are insufficient.
- Rebuilding mixed content from HTML plus images: DeskFlow should preserve the
  application's offered alternatives, not invent a new document.
- Partial fallback when a snapshot is oversized: can create a plausible but
  silently incomplete paste.

## Deferred

- Google Docs to Word and Word to Google Docs fidelity.
- SVG, metafiles, Office-private formats, and selective additional registered
  formats pending evidence from the required acceptance matrix.
- Clipboard protocol negotiation for mixed DeskFlow versions.
