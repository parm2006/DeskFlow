# Plan 003: Integrate v2 sync and validate Google Docs and Word

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If a
> STOP condition occurs, stop and write a handback; do not improvise. When done,
> update this plan's status row in the effort README.
>
> **Drift check (run first)**: `git diff 15a8092efe7ea21cc865f643be046ce546207bad -- app/clipboard_handler.py app/client.py app/server.py app/latest_wins_sender.py app/clipboard_formats.py app/windows_clipboard.py tests/test_clipboard_scheduling.py tests/test_file_paste_clipboard.py tests/test_windows_clipboard.py docs/plans/security-revamp/VALIDATION.md docs/plans/security-revamp/VALIDATION-RESULTS.md docs/superpowers/specs/2026-07-21-portable-clipboard-sync-design.md`
> Also confirm Plans 001 and 002 are marked DONE and their focused tests pass.

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: `001-build-bounded-ordered-snapshot.md`, `002-add-windows-ordered-clipboard-adapter.md`
- **Planned at**: revision `15a8092efe7ea21cc865f643be046ce546207bad`, 2026-07-21

## Why this matters

The pure codec and native adapter do not improve user behavior until the live
poller forwards every local clipboard sequence and both peers use the ordered
v2 message. This plan makes that switch while preserving latest-wins scheduling,
file clipboard authority, injection race handling, privacy-safe logs, and
connection survival after invalid content.

## Current state

- `app/clipboard_handler.py:45-57` owns version 1 fixed-key encoding.
- `app/clipboard_handler.py:66-69` stores text/image hashes used for both change
  detection and remote-loop suppression.
- `app/clipboard_handler.py:116-238` decodes and publishes remote formats in the
  fixed order text, DIB, HTML, RTF. It records the injected sequence before the
  100 ms settle delay so a newer user copy remains pending; preserve that race
  guarantee.
- `app/clipboard_handler.py:311-344` notices Windows sequence changes but sends
  only when text or DIB hashes differ. HTML/RTF-only changes are dropped.
- `app/client.py:395-403` and `app/server.py:346-354` submit raw snapshots to
  `LatestWinsSender`, encode on its worker, send `clipboard_sync`, and inject
  received dictionaries.
- `app/latest_wins_sender.py` bounds outbound work to one active and one
  replaceable pending value. Do not change this policy.
- `tests/test_clipboard_scheduling.py` covers codec placement and peer routing.
- `tests/test_file_paste_clipboard.py:32-119` covers file availability after
  remote injection and the user-copy-during-settle race.
- `docs/plans/security-revamp/VALIDATION.md:265-282` has a generic ordinary
  clipboard section that does not yet require mixed Google Docs content.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Clipboard integration | `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_formats tests.test_windows_clipboard tests.test_clipboard_scheduling tests.test_file_paste_clipboard tests.test_latest_wins_sender -v` | all tests pass |
| File regressions | `.\venv\Scripts\python.exe -m unittest tests.test_file_paste_manifest tests.test_file_paste_routing tests.test_file_paste_availability tests.test_file_paste_service -q` | all tests pass |
| Full tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | all tests pass |
| Compile | `.\venv\Scripts\python.exe -m compileall -q app tests run.py` | exit 0 |
| Patch hygiene | `git diff --check` | no output |

## Scope

**In scope**:

- `app/clipboard_handler.py`
- `app/client.py`
- `app/server.py`
- `tests/test_clipboard_scheduling.py`
- `tests/test_file_paste_clipboard.py`
- `docs/plans/security-revamp/VALIDATION.md`
- `docs/plans/security-revamp/VALIDATION-RESULTS.md` (only when physical tests
  are actually run)
- `docs/plans/portable-clipboard-sync/README.md` (status only)

**Read-only dependencies; do not modify unless a STOP condition is resolved by
replanning**:

- `app/clipboard_formats.py`
- `app/windows_clipboard.py`
- `app/latest_wins_sender.py`
- `app/network.py`
- file-transfer modules

**Out of scope**:

- Google Docs to Word or Word to Google Docs fidelity
- arbitrary/private formats, SVG, metafiles, shell formats, OLE, and resource
  downloading
- network frame size, encryption, pairing, and file-transfer protocol changes
- clipboard-history UI or application-specific browser/Word automation

## Required live behavior

The handler receives a `WindowsClipboardAdapter` dependency, defaulting to the
real adapter. It retains lock retries, polling lifecycle, file availability,
and secure wipe behavior.

Local sequence handling:

1. Ignore polling while a remote injection is active.
2. On a new sequence, store the observed sequence and update `CF_HDROP`
   availability.
3. If `CF_HDROP` is available, do not capture or send ordinary formats.
4. Otherwise capture one ordered portable snapshot. Every valid non-empty
   snapshot is submitted, including HTML-only, RTF-only, PNG-only, DIBV5-only,
   or byte-identical repeat copies.
5. A rejected/oversized capture logs a safe reason and does not affect the next
   sequence.

Remote injection:

1. Decode and validate the entire v2 message before opening or emptying the
   clipboard.
2. Set the injection guard, publish through the adapter, and read the exact
   sequence produced by DeskFlow.
3. During the settle delay, retain only that injected sequence as handled. A
   larger sequence produced by a user remains pending for the poller.
4. Recalculate file availability and clear the guard in `finally`, even if its
   callback or publication fails.
5. A malformed, oversized, version 1, or unsupported-version body is ignored
   safely; the current clipboard and connection remain usable.

Remove text/image content hashes from detection and loop prevention. The local
Windows sequence is the authority; do not add payload fingerprints or content
to logs.

## Steps

### Step 1: Add failing sequence-authority tests

Extend `tests/test_clipboard_scheduling.py` using a fake adapter and deterministic
sequence source. Prove that each of these local snapshots is submitted:

- HTML-only
- RTF-only
- PNG-only
- DIBV5-only
- mixed entries in non-default order
- the same snapshot copied in two distinct Windows sequences

Prove that a `CF_HDROP` sequence updates file availability but does not call
ordinary capture or submission.

**Verify**: clipboard integration tests fail for the old hash/fixed-format
behavior, not fake setup.

### Step 2: Refactor the handler to sequence-driven ordered snapshots

Inject the adapter and replace `_read_clipboard()` fixed queries with adapter
capture under the existing five-attempt lock retry policy. Remove
`last_text_hash`, `last_image_hash`, `_get_hash()`, and MD5 import/use.

Keep polling free of compression/network sends: it submits the immutable raw
snapshot to the existing `LatestWinsSender` callback.

When `CF_HDROP` is true, preserve the boolean-only file callback and never read
or serialize file paths through the ordinary path.

**Verify**: sequence-authority tests, file clipboard tests, and latest-wins tests
pass.

### Step 3: Add failing v2 routing and atomic-injection tests

Update peer scheduling tests to expect the full ordered version 2 message from
both client and server. Test that sender input is not mutated and compression
still runs on the latest-wins worker, not the poller.

Add receiver tests for:

- exact source order reaching adapter publication
- invalid Base64/zlib, duplicate/unknown kind, size overflow, version 1, and
  unsupported version leaving `EmptyClipboard`/publish untouched
- successful injection not bouncing back
- user copy during injection settle remaining pending
- publication or file-availability callback failure clearing the guard
- a valid copy succeeding after a rejected message

**Verify**: focused tests fail for missing v2 routing/injection behavior.

### Step 4: Switch both peers to v2 and atomic publication

Have `DeskFlowClient._send_clipboard_snapshot()` and
`DeskFlowServer._send_clipboard_snapshot()` call the Plan 001 encoder and send
its complete message. Do not mutate snapshots or append old fixed keys.

Have both receive callbacks pass the complete message to handler injection.
Decode before setting the injection guard or opening the clipboard; log a safe
warning and return on validation failure. Publish through the Plan 002 adapter
and preserve the current injected-sequence race guarantee.

Remove the old codec functions/constants from `clipboard_handler.py` after all
callers and tests move. Do not keep dual schemas or silently downgrade.

**Verify**: clipboard integration, file regressions, full tests, compile, and
patch hygiene all pass.

### Step 5: Make validation match the accepted product scope

Rewrite Section 9 of `docs/plans/security-revamp/VALIDATION.md` so it requires,
in both directions:

- Google Docs plain/Unicode text
- Google Docs formatted headings, color, links, and lists
- one selected Google Docs inline image
- one Google Docs selection containing formatted text and one or more images
- a small Google Docs table containing text and an image
- copying the same Google Docs selection twice
- Word formatted text, selected image, and mixed text/image as secondary cases
- screenshot, rapid latest-wins, oversize recovery, file-boundary, and
  disconnect/reconnect regressions

Label Google Docs to Word and Word to Google Docs as observations only. Add a
privacy-safe diagnostic instruction that records format kind, order, and byte
count—not content—if a required same-application case fails.

**Verify**: `rg -n "Google Docs|Word|observation|format.*order|clipboard contents" docs\plans\security-revamp\VALIDATION.md` shows every required scope statement.

### Step 6: Run the physical two-PC acceptance gate

Install the same new revision on both PCs and execute the revised Section 9
server-to-client and client-to-server. Keep both logs visible. Record only
PASS/FAIL/NOT RUN and privacy-safe observations in `VALIDATION-RESULTS.md`.

If Google Docs mixed formatted text plus images passes in both directions, run
the secondary Word and regression cases. If it fails, first prove from safe
diagnostics whether the six allowed formats, source order, and byte counts were
captured and republished identically.

**Verify**: the Section 9 result in `VALIDATION-RESULTS.md` is PASS, with every
required Google Docs case executed in both directions. If hardware is
unavailable, do not mark the effort DONE; hand back as implementation-complete,
physical-validation-pending.

## Test plan

Automated tests must cover:

- all six kinds and non-default order through both peer routes
- HTML/RTF/PNG/DIBV5-only local sequence changes
- same bytes copied in distinct sequences
- latest-wins sender behavior unchanged
- file sequence excluded from ordinary serialization
- full validation before clipboard mutation
- malformed, oversized, unsupported-version, and post-failure recovery
- injected sequence suppression and newer user sequence preservation
- injection guard cleanup on every exception path

Physical tests must cover the exact Google Docs, Word, and regression matrix in
the approved design and revised Validation Section 9.

## Done criteria

- [ ] Both peers send and receive only the ordered clipboard v2 schema.
- [ ] HTML/RTF/PNG/DIBV5-only and repeated identical copies are forwarded.
- [ ] Source order reaches `SetClipboardData` unchanged.
- [ ] Invalid or oversized snapshots leave the clipboard and connection usable.
- [ ] `CF_HDROP` remains boolean-only in ordinary clipboard routing.
- [ ] Latest-wins and user-copy-during-injection guarantees remain covered.
- [ ] Focused tests, file regressions, full tests, compile, and patch hygiene
  pass.
- [ ] Revised physical Google Docs tests pass in both directions and results are
  recorded; Word is secondary, and cross-application tests are observations.
- [ ] No files outside the in-scope list are modified except prior-plan
  dependencies already committed before this plan starts.

## STOP conditions

Stop if:

- a required Google Docs mixed selection fails after safe diagnostics prove all
  six allowlisted formats, source order, and byte counts match end to end.
- success appears to require arbitrary registered formats, HTML resource
  downloading/rewriting, SVG/metafiles, shell data, OLE, or an `IDataObject`
  proxy.
- switching schemas requires network frame, encryption, or file-transfer
  changes.
- version 2 breaks input/control connectivity rather than only clipboard
  compatibility with an old peer.
- a user copy during injection can only be preserved by reintroducing content
  hashes or suppressing more than DeskFlow's exact injected sequence.

On stopping, write a handback with the failing same-application case, safe
format order/count evidence, automated test state, and the smallest unresolved
design fork. Do not broaden the protocol inside this plan.

## Maintenance notes

Google Docs to Google Docs is the fidelity gate. Word to Word is a secondary
guardrail. Cross-application behavior is not evidence that DeskFlow's transport
is broken unless the same copy/paste succeeds locally between those applications.
