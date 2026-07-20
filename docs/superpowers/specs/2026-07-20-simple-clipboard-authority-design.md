# Simple Clipboard Authority Repair

## Context

Commit `daa43a6` restores the tracked source tree to the `df13d7a` baseline.
The replacement must solve the observed copy delay, lost local copies, and
same-machine paste failures without rebuilding the rejected split-lane
clipboard-offer protocol.

The rejected design introduced three causal regressions:

1. Both peers sent their existing ordinary clipboard during connection.
2. Clipboard status and content traveled independently, so delayed content
   could overwrite a newer local copy.
3. Ctrl+V read the Windows clipboard and sent network messages inside a
   low-level keyboard hook.

## Required behavior

- A successful copy from the screen currently controlled by DeskFlow becomes
  the clipboard authority.
- One Ctrl+C must produce one acknowledged copy event and a usable paste. The
  user must never need a second or third Ctrl+C to make DeskFlow notice it.
- Physical clipboard changes on the inactive computer do not replace the
  active screen's clipboard authority.
- Moving between screens does not copy, clear, or replace clipboard content.
- DeskFlow sends no ordinary clipboard content during connection startup.
- A delayed remote payload never overwrites a newer local clipboard change.
- Same-machine Ctrl+C and Ctrl+V retain native Windows behavior.
- File-to-text, text-to-file, screenshot, rich text, repeated-copy, empty-
  clipboard, and reconnect transitions remain deterministic.
- File-paste interception performs no clipboard reads, sleeps, retries, or
  network operations in the keyboard-hook callback.
- Logs identify authority, kind, Windows sequence, and transition outcome but
  never include clipboard content or full file paths.

## Architecture

### 1. Clipboard handler

`ClipboardHandler` remains the only component that touches the Windows
clipboard. On startup it records the current Windows clipboard sequence and
file status without transmitting ordinary content.

The poller classifies each new Windows sequence as `ordinary` or `files`.
It reports the classification even when ordinary content matches a previous
copy, but the ordinary payload continues through the existing latest-wins data
sender. The handler accepts an `active` flag. It records changes while inactive
but does not publish them as user copy events.

Before injecting remote ordinary content, the handler opens the clipboard and
checks the sequence while holding the clipboard lock. If the sequence differs
from the last processed sequence, the handler closes the clipboard and rejects
the remote payload. This makes an unprocessed local Ctrl+C win atomically.
After a successful injection, the handler records DeskFlow's sequence before
closing the clipboard. It does not sleep while owning injection state.

### 2. Clipboard authority

Each DeskFlow peer stores one authority value: `local`, `remote`, or `unknown`.
Only a classified copy event from the active screen sets `local`. A received
file status or accepted ordinary payload sets `remote`. Screen switching alone
does not change authority.

An incoming ordinary payload is rejected when a newer active local copy owns
authority. It is also rejected when the handler detects an unprocessed local
Windows sequence. The active-screen rule makes this ordering deterministic:
the inactive peer cannot create a competing valid copy.

This state is independent from transport and Windows APIs. A later clipboard
listener can replace polling without changing authority rules, and a later file
FIFO can use the authority result without changing ordinary clipboard code.

### 3. File-versus-ordinary status

The existing control-lane file-availability message remains small and
independent from ordinary clipboard content. Each valid active-screen copy
reports `ordinary` or `files`; the message does not correlate or buffer payload
data.

Ctrl+C creates a short-lived `copy pending` state in the pure in-memory paste
coordinator. While pending, Ctrl+V follows native Windows behavior. A confirmed
clipboard classification clears the pending state and applies the actual kind.
If no clipboard change follows, the pending state expires and restores the
previous file state.

This handles an immediate file-to-text Ctrl+C/Ctrl+V sequence without opening
the clipboard from the hook.

### 4. Keyboard hook

The hook recognizes Ctrl, C, and V, updates coordinator state, and decides
whether to suppress V. Every operation is bounded, in-memory work. The hook
never calls `OpenClipboard`, waits, sleeps, hashes content, or sends a network
message.

Injected key events remain excluded so DeskFlow's own paste injection cannot
create copy or paste intent.

## Data flow

### Active-screen ordinary copy

1. Ctrl+C marks copy pending without suppressing the key.
2. Windows updates the active screen's clipboard sequence.
3. The poller classifies the sequence as ordinary.
4. Local authority becomes `local`; copy pending clears; file interception
   disables.
5. The ordinary snapshot enters the latest-wins data sender.
6. The inactive peer accepts it only if no newer valid local change exists.

### Active-screen file copy

1. Ctrl+C marks copy pending.
2. The poller classifies the sequence as files.
3. Local authority becomes `local`; copy pending clears.
4. The small file-status message enables file-paste interception where needed.
5. Ctrl+V requests a manifest; ordinary clipboard injection does not run.

### Delayed remote ordinary payload

1. A remote payload arrives after the user has pressed Ctrl+C locally.
2. If the local copy is already classified, local authority rejects the
   payload.
3. If the poller has not classified it, the atomic Windows sequence check
   rejects the payload.
4. The local clipboard remains unchanged in both cases.

## Error handling

- A locked clipboard stays pending and retries from the poller; the keyboard
  hook continues immediately.
- Failed remote injection preserves local content and logs a reason code.
- Failed network sends stay inside the latest-wins sender and never block the
  hook.
- Disconnect resets remote authority and interception state but preserves the
  baseline disconnect policy until physical validation proves a change is
  needed.

## Verification

Tests must fail on the restored baseline before production changes cover them:

1. One Ctrl+C and one Windows sequence change produce exactly one acknowledged
   copy event; no repeated keypress is required.
2. Startup records the sequence without sending ordinary content.
3. Ctrl+V never invokes clipboard or network callbacks.
4. Copy pending allows native paste and expires to the previous state.
5. An active local copy rejects a delayed remote payload.
6. An unprocessed local Windows sequence atomically rejects remote injection.
7. Inactive-machine clipboard changes do not publish.
8. File-to-text and text-to-file transitions update interception once.
9. Repeated text, rich-only content, screenshots, and empty content remain
   ordinary copy events.
10. Reconnect starts without exchanging stale ordinary content.
11. The full automated suite, compilation, and patch-integrity checks pass.

Physical two-PC validation then repeats same-machine copy/paste, immediate
file-to-text, text-to-file, screenshot, multi-file, large-file, duplicate-file,
failure-toast, reconnect, and input-responsiveness cases. FIFO work remains
blocked until this gate passes.

## Excluded work

- No split-lane clipboard offer/payload correlation.
- No Windows raw-input rewrite or asynchronous COM clipboard proxy.
- No file FIFO in this repair.
- No attempt to synchronize independent physical copies from both computers at
  the same time; the active screen is the sole copy authority.
