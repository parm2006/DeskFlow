# Plan 002: Add ordered Windows capture and publication

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition occurs, stop and write a handback; do not improvise. When done,
> update this plan's status row in the effort README.
>
> **Drift check (run first)**: `git diff 15a8092efe7ea21cc865f643be046ce546207bad -- app/clipboard_handler.py app/windows_clipboard.py app/clipboard_formats.py tests/test_file_paste_clipboard.py tests/test_windows_clipboard.py docs/superpowers/specs/2026-07-21-portable-clipboard-sync-design.md`
> Also confirm Plan 001 is marked DONE and its focused tests pass.

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: `001-build-bounded-ordered-snapshot.md`
- **Planned at**: revision `15a8092efe7ea21cc865f643be046ce546207bad`, 2026-07-21

## Why this matters

Windows clipboard fidelity depends on the order in which formats are offered.
The current handler queries four formats in DeskFlow's preferred order and
publishes them in another fixed order. A narrow native adapter must enumerate,
bound, and republish the approved formats without admitting shell or private
application data.

## Current state

- `app/clipboard_handler.py:64-74` stores `CF_HDROP` and registers only `HTML
  Format` and `Rich Text Format`.
- `app/clipboard_handler.py:242-277` uses `IsClipboardFormatAvailable` and
  `GetClipboardData` for text, DIB, HTML, and RTF. It cannot preserve source
  order and has no pre-copy native binary bound.
- `app/clipboard_handler.py:196-211` publishes text, DIB, HTML, then RTF.
- `app/clipboard_handler.py:291-309` owns file availability and file-selection
  reads. Leave that responsibility in the handler/file subsystem.
- `tests/test_file_paste_clipboard.py` patches `app.clipboard_handler` directly;
  Plan 003, not this plan, migrates those live-handler tests.
- `app/windows_virtual_files.py:110-123` is the repository exemplar for
  registering Windows clipboard formats, but its OLE/file responsibilities are
  out of scope here.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Adapter tests | `.\venv\Scripts\python.exe -m unittest tests.test_windows_clipboard -v` | all tests pass |
| Codec + adapter | `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_formats tests.test_windows_clipboard -q` | all tests pass |
| Full tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | all tests pass |
| Compile | `.\venv\Scripts\python.exe -m compileall -q app tests run.py` | exit 0 |
| Patch hygiene | `git diff --check` | no output |

## Scope

**In scope**:

- `app/windows_clipboard.py` (new)
- `tests/test_windows_clipboard.py` (new)
- `docs/plans/portable-clipboard-sync/README.md` (status only)

**Read-only references; do not modify**:

- `app/clipboard_formats.py`
- `app/clipboard_handler.py`
- `app/windows_virtual_files.py`
- `tests/test_file_paste_clipboard.py`
- `docs/superpowers/specs/2026-07-21-portable-clipboard-sync-design.md`

**Out of scope**:

- switching `ClipboardHandler` to the adapter
- peer routing and protocol fallback
- `CF_HDROP`, shell formats, OLE, delayed-rendering ownership, and file paths
- parsing, sanitizing, rewriting, or transcoding HTML/RTF/images
- clipboard history, cloud clipboard, or application automation

## Required adapter boundary

Create `WindowsClipboardAdapter` with dependencies injectable enough for unit
tests. It owns only these mappings:

| Stable kind | Windows format |
|---|---|
| `unicode_text` | `CF_UNICODETEXT` |
| `html` | registered `HTML Format` |
| `rtf` | registered `Rich Text Format` |
| `png` | registered `PNG` |
| `dib` | `CF_DIB` |
| `dibv5` | `CF_DIBV5` |

The adapter provides one single-attempt capture and one single-attempt publish
operation. The live handler will retain bounded lock retry timing in Plan 003.

Capture requirements:

- Clipboard is already open, or the adapter opens it exactly once according to
  one clearly documented API contract; do not mix both ownership styles.
- Enumerate with `EnumClipboardFormats(0)` until zero and keep approved formats
  in returned order.
- Ignore every non-allowlisted format without reading it.
- Canonicalize `CF_UNICODETEXT` to UTF-16LE bytes with exactly one terminating
  two-byte NUL and reject malformed or oversized text.
- For HTML, RTF, PNG, DIB, and DIBV5, use `GetClipboardData`, `GlobalSize`,
  `GlobalLock`, bounded `string_at`, and `GlobalUnlock` behind a small injectable
  native-memory collaborator. Check `GlobalSize` against both the format's
  remaining per-format and aggregate budget before copying bytes.
- If any selected format or the complete snapshot is invalid/oversized, reject
  the whole capture. Do not return a partial snapshot.

Publication requirements:

- Validate the complete `ClipboardSnapshot` before `EmptyClipboard`.
- Call `SetClipboardData` in snapshot entry order.
- Decode canonical UTF-16LE text to the string form required by pywin32.
- Publish all other formats as unchanged bytes under their mapped IDs.
- Never publish an unknown, duplicate, file, or shell format.

## Steps

### Step 1: Characterize pywin32 and native-memory seams with failing tests

Create fakes for format enumeration, registration, global-memory sizing/copy,
and publication. Add failing tests proving the registered names are exact,
enumeration order survives, unknown formats are not read, and publication calls
occur in source order.

Include an order that disagrees with the old fixed order, for example `PNG`,
`HTML Format`, `CF_UNICODETEXT`, `CF_DIBV5`.

**Verify**: adapter tests fail because the module/API is absent, not from a real
desktop clipboard dependency.

### Step 2: Implement the allowlisted format registry and enumeration

Register only HTML, RTF, and PNG. Map standard constants without registration.
Keep reverse ID lookup private and deterministic. If a registration fails,
raise a safe initialization error naming only the stable kind.

Enumerate all IDs to preserve relative order, but create entries only for the
six allowed IDs. Do not call `GetClipboardFormatName` for unknown IDs and do not
log them; an unknown registered name can itself contain private information.

**Verify**: registration, enumeration-order, and unknown-format tests pass.

### Step 3: Add failing bounded-read and Unicode tests

Cover `GlobalSize` rejection before byte copy, lock/unlock cleanup, aggregate
overflow, a read failure after an earlier valid entry, empty allowlisted offer,
Unicode canonicalization, malformed UTF-16, and exact byte preservation for
each opaque format.

Assert a rejected mixed snapshot returns/raises no usable partial result.

**Verify**: tests fail only for missing capture behavior.

### Step 4: Implement bounded capture

Keep native handle work in a small collaborator so pointer handling is isolated
and reviewable. Set explicit ctypes argument and result types. Never call
`ctypes.string_at` before a successful lock and size check. Always unlock in a
`finally` block when locking succeeded.

Use the constants and immutable model from `app.clipboard_formats.py`; do not
duplicate limits. Return entries in enumeration order.

**Verify**: all capture tests pass.

### Step 5: Add failing atomic-validation and publication-order tests

Cover all six formats, non-default order, malformed Unicode, unknown/duplicate
entries constructed through adversarial fixtures, and a validation failure.
Assert validation failure occurs before `EmptyClipboard`.

Also characterize a mid-publication `SetClipboardData` failure. The adapter may
report failure after mutation; it must not retry by itself, pretend success, or
publish later entries.

**Verify**: tests fail only for missing publication behavior.

### Step 6: Implement ordered publication

Validate first, empty once, then publish in exact entry order. Keep opaque bytes
unchanged. Surface safe typed errors to the handler; do not log content in this
module.

**Verify**: run adapter tests, codec + adapter tests, compile, full tests, and
patch hygiene. All must pass.

## Test plan

`tests/test_windows_clipboard.py` must cover:

- exact registration and stable-ID mapping
- arbitrary source order retained through capture and publication
- unknown/private/shell IDs ignored without reads or name lookup
- HTML/RTF/PNG/DIB/DIBV5 opaque byte preservation
- Unicode canonical UTF-16LE round trip
- `GlobalSize` checked before copy and aggregate bounds enforced
- lock/unlock cleanup on success and exceptions
- complete-snapshot rejection rather than partial fallback
- validation before `EmptyClipboard`
- safe behavior on mid-publication failure

All tests must run headlessly with fakes; do not read or mutate the developer's
actual clipboard.

## Done criteria

- [ ] The adapter knows exactly six portable formats and no generic format path.
- [ ] Capture retains `EnumClipboardFormats` order and bounds memory before copy.
- [ ] Publication validates first and calls `SetClipboardData` in source order.
- [ ] Opaque bytes survive unchanged and Unicode has one documented canonical
  representation.
- [ ] Adapter, codec, full tests, compile, and patch hygiene pass.
- [ ] No file outside the in-scope list is modified except the README status.

## STOP conditions

Stop if:

- pywin32 converts or destroys HTML, RTF, PNG, DIB, or DIBV5 bytes before the
  adapter can obtain the underlying `HGLOBAL`.
- any approved format is not backed by movable global memory in the observed
  Google Docs/Word clipboard and therefore cannot use the bounded read path.
- `SetClipboardData` cannot publish registered PNG or DIBV5 bytes using the
  existing pywin32 dependency.
- reliable publication order requires delayed rendering or an OLE data object.
- handling capture correctly requires reading unknown, shell, or file formats.

Write a handback with the specific Win32 API behavior and a minimal reproducer.
Do not add a generic format mirror, OLE proxy, or new dependency.

## Maintenance notes

The adapter is deliberately narrower than the Windows clipboard API. Reviewers
should reject convenience methods that accept an arbitrary numeric format ID or
registered name from the network.
