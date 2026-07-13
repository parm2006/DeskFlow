# Explorer-truthful file paste progress

## Goal

Keep the DeskFlow toast visible on both computers until Windows Explorer finishes consuming the virtual files. Report measured work instead of treating network staging as final paste completion. Position each toast fully inside the work area of the monitor that owns the DeskFlow window.

GitHub issue #2 defers the optional behavior of hiding the destination toast while Explorer shows its native progress dialog.

## Current failure

DeskFlow currently reports three different boundaries as one operation:

1. The source passes bytes to its file-lane socket.
2. The destination receives, stages, and verifies those bytes.
3. Explorer reads the virtual `IStream` and writes the destination file.

The toast reaches 100 percent at boundary 2. Explorer may still be waiting for a duplicate-name decision or copying at boundary 3. Cancelling the stream makes Explorer show its own `Error Copying File or Folder: Unspecified error` dialog. A later socket exception can also obscure an intentional cancellation unless terminal state is preserved.

The toast-positioning code also mixes Win32 physical work-area coordinates with Tk geometry coordinates. Mixed display scaling can place the destination toast beyond the right edge.

## Chosen design

### Explorer-only user-facing progress

Keep one job identity and two internal counters:

- **Network receipt**: unique uncompressed bytes received and verified by DeskFlow. Keep this for diagnostics, integrity, and rate control; do not use it as the toast percentage.
- **Copying in Explorer**: unique bytes returned to Explorer from `IStream.Read`. This is destination-consumption progress.

Before Explorer requests content, both toasts show `Waiting for Windows Explorer` with an indeterminate bar and no percentage, throughput, or ETA. This includes network transfer, staging, verification, and any conflict dialog. Once reads begin, both show only the Explorer-consumption percentage, measured throughput, and ETA. Never expose network progress as the main copy bar or interpolate progress from configured bandwidth or file size alone.

Track unique byte intervals per manifest item because Explorer may seek, clone a stream, or reread a range. Count the union of returned ranges; never add duplicate reads twice. Directories contribute no content bytes.

### Cross-computer status

The destination owns Explorer progress. After each bounded progress increment, it sends a small authenticated `paste_progress` event over the existing file lane:

- job ID
- unique bytes consumed
- total file bytes
- measured bytes per second
- phase

The source applies these events to its existing `TransferController`. Both toasts therefore display the same destination-owned Explorer progress. Rate-limit events by byte and time thresholds so progress cannot interfere with input or clipboard traffic.

### Authoritative operation lifecycle

Add a minimal Windows COM bridge that exposes `IDataObjectAsyncCapability` alongside the existing `IDataObject` and `IStream` behavior. pywin32 does not provide a built-in gateway for this interface.

The bridge reports:

- `StartOperation`: Explorer started asynchronous extraction.
- `IStream.Read`: actual ranges returned to Explorer.
- `EndOperation(S_OK, ...)`: Explorer reports successful extraction.
- `EndOperation(error, ...)`: Explorer reports cancellation or failure.

Python continues to own manifests, TLS, validation, compression, staging, and UI. The bridge contains no networking and accepts only callbacks and already-validated descriptors. Package it with the Windows application and verify its architecture matches the Python process.

If Explorer does not negotiate `IDataObjectAsyncCapability`, fall back to measured `IStream.Read` coverage. Mark completion as `Explorer consumed all bytes`; do not claim that Windows reported success. Keep this distinction in logs, while the toast uses concise user-facing wording.

### Cancellation

DeskFlow Cancel sends one job-scoped cancellation request. Both peers enter `Cancelling` and disable the button. The source stops producing new chunks; the destination invalidates partial streams and acknowledges cancellation. Both toasts close only after both peers have acknowledged the terminal state.

Explorer may still display its native error dialog when its requested stream is deliberately interrupted. DeskFlow cannot dismiss or alter that Explorer-owned dialog. It must classify the operation as cancelled, never failed, and must not require a second DeskFlow Cancel click.

### DPI-safe placement

Position the toast after its native window exists:

1. Obtain its `HWND`.
2. Use `MonitorFromWindow(..., MONITOR_DEFAULTTONEAREST)`.
3. Read that monitor's `rcWork` with `GetMonitorInfoW`.
4. use `GetDpiForWindow` and one consistent physical-to-Tk conversion.
5. Clamp the final rectangle so all four toast edges remain inside `rcWork`.

Do not derive placement from the primary screen width, global screen ratios, or a different DeskFlow window.

## State model

`PREPARING -> WAITING_FOR_EXPLORER -> PASTING -> VERIFYING_RESULT -> COMPLETED`

Any nonterminal phase may enter `CANCELLING`, followed by `CANCELLED`. Protocol, validation, disk, or COM errors enter `FAILED`. Terminal states are immutable.

The toast remains visible on both machines through every nonterminal phase. Completed hides after three seconds. Cancelled hides immediately after peer acknowledgment. Failed remains for eight seconds.

## Failure handling

- Reject progress for unknown or terminal job IDs.
- Validate monotonic covered-byte totals and declared total size.
- Ignore duplicate or stale progress frames.
- Preserve the last truthful phase when the file lane disconnects and show a specific connection failure.
- Never allow UI callbacks or native callbacks to block the file lane, Explorer's COM thread, or input handling.
- Keep file paths out of progress events and user-visible error details.

## Verification

Automated tests must cover interval-union accounting, stream clones and seeks, progress frame validation, terminal-state immutability, cancellation acknowledgment, async lifecycle result mapping, fallback completion, and DPI clamping at 100%, 125%, 150%, and 200% scaling.

Two-computer tests must cover both directions, a file large enough to observe both stages, duplicate-name Replace/Don't copy/Cancel, DeskFlow Cancel during network receipt and Explorer consumption, mixed DPI, taskbar placement, reconnect, and continued text/screenshot/input responsiveness.

## Non-goals

- Hiding the destination toast while Explorer shows native progress; deferred to issue #2.
- Replacing or controlling Explorer's native copy dialog.
- Dismissing Explorer-owned error dialogs.
- User-facing multi-destination queue support; deferred to issue #1 unless the native bridge resolves its prerequisite.
