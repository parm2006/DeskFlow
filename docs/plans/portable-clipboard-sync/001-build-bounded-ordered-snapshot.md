# Plan 001: Build the bounded ordered clipboard snapshot

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition occurs, stop and write a handback; do not improvise. When done,
> update this plan's status row in the effort README.
>
> **Drift check (run first)**: `git diff 15a8092efe7ea21cc865f643be046ce546207bad -- app/clipboard_handler.py app/network.py app/clipboard_formats.py tests/test_clipboard_scheduling.py tests/test_clipboard_formats.py docs/superpowers/specs/2026-07-21-portable-clipboard-sync-design.md`
> If the current clipboard codec or network frame limit differs from the
> excerpts below, stop and reconcile the design before implementation.

## Status

- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Planned at**: revision `15a8092efe7ea21cc865f643be046ce546207bad`, 2026-07-21

## Why this matters

The current fixed-key payload cannot retain Windows clipboard format order and
has no whole-snapshot raw-byte bound. A small, pure protocol module makes the
security and compatibility rules testable before native clipboard behavior is
changed.

## Current state

- `app/clipboard_handler.py:13-14` defines 5 MiB rich and 50 MiB image limits.
- `app/clipboard_handler.py:22-42` has a safe bounded zlib decoder that rejects
  invalid Base64, truncated streams, oversized plaintext, and trailing data.
  Preserve those properties in the new decoder.
- `app/clipboard_handler.py:45-57` encodes the fixed keys `text`, `image`,
  `html`, and `rtf`; dictionary order does not represent source clipboard order.
- `app/network.py:21` limits a JSON frame to 64 MiB.
- `tests/test_clipboard_scheduling.py:31-69` is the current codec test style.
- There is no `app/clipboard_formats.py` or `tests/test_clipboard_formats.py`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| New codec tests | `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_formats -v` | all tests pass |
| Clipboard regressions | `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_formats tests.test_clipboard_scheduling -q` | all tests pass |
| Full tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | all tests pass |
| Compile | `.\venv\Scripts\python.exe -m compileall -q app tests run.py` | exit 0 |
| Patch hygiene | `git diff --check` | no output |

## Scope

**In scope**:

- `app/clipboard_formats.py` (new)
- `tests/test_clipboard_formats.py` (new)
- `docs/plans/portable-clipboard-sync/README.md` (status only)

**Read-only references; do not modify**:

- `app/clipboard_handler.py`
- `app/network.py`
- `tests/test_clipboard_scheduling.py`
- `docs/superpowers/specs/2026-07-21-portable-clipboard-sync-design.md`

**Out of scope**:

- live clipboard capture, publication, polling, and peer routing
- file clipboard and virtual-file code
- changing `MAX_MESSAGE_SIZE`
- version negotiation or version 1 downgrade support

## Required model and wire contract

Create immutable `ClipboardEntry(kind: str, data: bytes)` and
`ClipboardSnapshot(entries: tuple[ClipboardEntry, ...])` values, or equivalent
frozen types. Preserve entry order. Reject unknown kinds, duplicate kinds,
non-bytes data, empty snapshots, and more than six entries.

The exact allowlist is:

```text
unicode_text, html, rtf, png, dib, dibv5
```

Use these raw limits from the approved design:

```text
unicode_text/html/rtf: 5 MiB each
png/dib/dibv5:        32 MiB each
complete snapshot:    40 MiB
encoded JSON message: 60 MiB
```

`encode_clipboard_message(snapshot)` returns a new dictionary with `type` set
to `clipboard_sync`, `version` set to integer `2`, and ordered `formats` entries.
Each format entry has only `kind`, exact `raw_size`, and zlib-compressed,
Base64-encoded `data`.

`decode_clipboard_message(message)` accepts only that shape and returns the
immutable snapshot. Reject booleans where integers are required, unknown or
extra fields, unsupported versions, duplicate kinds, declared-size mismatch,
invalid Base64/zlib, non-EOF streams, trailing bytes, per-format overflow,
aggregate overflow, and messages whose canonical compact JSON encoding exceeds
60 MiB. Never allocate `raw_size` bytes based only on the declaration; inflate
with the smaller of the per-format and remaining aggregate limits plus one byte.

## Steps

### Step 1: Add failing model and ordering tests

Create `tests/test_clipboard_formats.py`. First cover construction invariants,
allowlist enforcement, immutable bytes, duplicate rejection, and preservation
of a deliberately non-default order such as `html`, `png`, `unicode_text`,
`dibv5`.

**Verify**: run the new codec tests. They must fail because the module does not
exist or the required model is missing, not because of unrelated setup errors.

### Step 2: Implement the ordered model and constants

Create `app/clipboard_formats.py` with one authoritative format catalog and the
per-format/aggregate/encoded limits. Keep it platform-independent: it must not
import `win32clipboard`, `ctypes`, `app.client`, or `app.server`.

Make validation errors use a dedicated exception such as
`ClipboardPayloadError(ValueError)`. Error text may name a format kind and a
validation reason but never include clipboard content.

**Verify**: model tests pass; codec tests that have not been implemented yet
still fail for their intended missing behavior.

### Step 3: Add adversarial codec tests

Test a valid six-format round trip and each rejection listed in “Required model
and wire contract.” Include a compression-bomb case, aggregate limit across
multiple individually valid entries, mismatched `raw_size`, duplicate format,
unsupported version, unknown field, and compressed trailing data.

Patch constants to small values in tests or generate compact fixtures; do not
allocate tens of MiB merely to test arithmetic. Assert the input snapshot and
message dictionaries are not mutated.

**Verify**: new tests fail only for missing codec behavior.

### Step 4: Implement bounded v2 encoding and decoding

Compress outside any Windows clipboard concern. Compute all raw bounds before
compression. After constructing the full message, measure canonical compact
UTF-8 JSON bytes and reject above 60 MiB. Decode in list order and validate the
complete message before returning any snapshot.

Do not expose a “skip invalid entry” mode. One invalid entry rejects the whole
message.

**Verify**: run new codec tests, clipboard regressions, compile, full tests, and
patch hygiene. All must pass.

## Test plan

`tests/test_clipboard_formats.py` must cover:

- valid ordered six-format round trip
- model immutability and input non-mutation
- unknown, duplicate, empty, and too-many formats
- wrong top-level and entry field sets/types
- unsupported protocol version
- invalid Base64/zlib, truncation, trailing data, and size mismatch
- per-format, aggregate raw, and encoded-message bounds
- highly compressible data exceeding the raw limit
- safe exception messages that omit fixture content

Use `tests/test_clipboard_scheduling.py:31-69` as the style exemplar, but do not
move or delete the version 1 functions yet.

## Done criteria

- [ ] Ordered immutable snapshots and the six-format allowlist exist in one
  platform-independent module.
- [ ] V2 encode/decode validates the whole message atomically and preserves
  order and opaque bytes.
- [ ] Raw and encoded bounds match the approved design.
- [ ] New codec tests, clipboard regressions, full tests, compile, and
  `git diff --check` pass.
- [ ] No file outside the in-scope list is modified except the README status.

## STOP conditions

Stop if:

- 40 MiB of worst-case raw data cannot fit below the existing 64 MiB network
  frame after zlib, Base64, and JSON overhead.
- A correct bounded decoder requires changing `app/network.py`.
- The implementation needs application-specific HTML, RTF, or image parsing.
- Existing tests import `ClipboardPayloadError` in a way that cannot coexist
  temporarily with the new module without modifying live production code.
- Any required format or limit differs from the approved design.

On stopping, write a handback that describes the observed conflict and the
smallest design choice needed. Do not choose a larger allowlist or frame size.

## Maintenance notes

Future portable formats must be added to the catalog, per-format limits, codec
tests, Windows ID mapping, and physical acceptance matrix together. Never add a
generic “registered format” escape hatch to this protocol.
