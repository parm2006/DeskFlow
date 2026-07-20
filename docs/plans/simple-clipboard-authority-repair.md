# Plan: Restore single-press clipboard authority and native paste reliability

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on.
> Use test-driven development: add one focused test, run it and observe the
> expected failure, make the smallest production change, then rerun it. If a
> STOP condition occurs, write a handback instead of improvising.
>
> **Drift check (run first)**:
> `git diff d731b83 -- app/clipboard_handler.py app/file_transfer/paste_coordinator.py app/file_transfer/hotkey.py app/client.py app/server.py tests/test_file_paste_clipboard.py tests/test_file_paste_availability.py tests/test_file_paste_hotkey.py tests/test_file_paste_routing.py tests/test_clipboard_scheduling.py`
> Expected before execution: no output. If any listed file changed, reconcile
> it against this plan before editing.

## Status

- **Effort**: M
- **Risk**: HIGH
- **Depends on**: `docs/superpowers/specs/2026-07-20-simple-clipboard-authority-design.md`
- **Planned at**: revision `d731b83`, 2026-07-20

## Why this matters

The rejected clipboard-offer implementation made Ctrl+C require repeated
keypresses, allowed delayed remote content to replace local content, and did
blocking clipboard/network work inside a global keyboard hook. Revision
`daa43a6` restored the tracked production and test tree to `df13d7a`. This plan
adds the smallest deterministic repair: only the active screen may publish a
copy, local changes beat delayed remote data, and keyboard hooks remain pure
in-memory state transitions.

## Current state

- `app/clipboard_handler.py:81-91` seeds `last_sequence_num` at startup and
  does not send ordinary startup content. Preserve this baseline behavior.
- `app/clipboard_handler.py:116-254` injects remote content, retries clipboard
  acquisition, and records the resulting sequence after the clipboard closes.
  It lacks an atomic pre-write guard against an unprocessed local sequence.
- `app/clipboard_handler.py:311-344` polls every 500 ms and publishes only
  changed text/image hashes. It has no active-screen gate and no per-sequence
  kind callback.
- `app/file_transfer/paste_coordinator.py:1-36` contains only in-memory Ctrl+V
  interception. Preserve this property while adding bounded copy-pending state.
- `app/file_transfer/hotkey.py:35-68` maps Ctrl and V. Extend it to map C; do
  not add Windows clipboard or network dependencies.
- `app/server.py:213-260` owns the authoritative screen-switch direction.
  `switching_to_client=False` means the server screen is active.
- `app/client.py:343-392` owns the client-side direction.
  `is_active=True` means the client screen is active.
- `app/server.py:345-375` and `app/client.py:394-414` route ordinary payloads
  and file availability without authority checks.
- Tests use `unittest`, `unittest.mock.patch`, small recording fakes, and direct
  `__new__` construction for routing tests. Match
  `tests/test_file_paste_clipboard.py`,
  `tests/test_file_paste_availability.py`, and
  `tests/test_file_paste_routing.py`.
- Error logs name exception types through `app.safe_errors.error_name`; never
  log clipboard content or full paths.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused clipboard tests | `.\venv\Scripts\python.exe -m unittest tests.test_clipboard_authority tests.test_file_paste_clipboard tests.test_file_paste_availability tests.test_file_paste_hotkey tests.test_file_paste_routing tests.test_clipboard_scheduling -q` | exit 0, `OK` |
| File subsystem | `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_file*.py" -q` | exit 0, `OK` |
| Full suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | exit 0, `OK` |
| Compile | `.\venv\Scripts\python.exe -m compileall -q app tests run.py` | exit 0, no output |
| Patch integrity | `git diff --check` | exit 0, no output |

## Scope

**In scope**:

- `app/clipboard_authority.py` (new)
- `app/clipboard_handler.py`
- `app/file_transfer/paste_coordinator.py`
- `app/file_transfer/hotkey.py`
- `app/client.py`
- `app/server.py`
- `tests/test_clipboard_authority.py` (new)
- `tests/test_file_paste_clipboard.py`
- `tests/test_file_paste_availability.py`
- `tests/test_file_paste_hotkey.py`
- `tests/test_file_paste_routing.py`
- `tests/test_clipboard_scheduling.py`
- the accepted design, this plan, and the focused handoff

**Out of scope**:

- `app/windows_virtual_files.py` and COM ownership code: this repair must not
  reintroduce asynchronous COM behavior.
- Manifest, sender, receiver, and transfer queue modules: keep file transport
  unchanged until clipboard validation passes.
- True file FIFO: begin only after the two-PC gate.
- Windows raw input or `AddClipboardFormatListener`: the baseline poller is
  sufficient for this repair.
- Independent physical copies on both computers: only the active screen may
  publish.

## Steps

### Step 1: Prove the authority rules independently

Create `app/clipboard_authority.py` only after
`tests/test_clipboard_authority.py` fails because the module or behavior is
absent. The state object must expose explicit operations for screen activity,
successful local copy, remote status, remote-payload acceptance, and reset.

Required invariants:

- a local copy changes authority only while the local screen is active;
- inactive physical changes cannot publish or claim authority;
- a remote status is accepted because only the active screen can send one;
- an active local copy blocks delayed remote payloads;
- switching screens alone preserves the last copy authority;
- reset returns `unknown` and inactive-safe state.

Keep this object free of Windows, network, clipboard-content, and timing APIs.

**Verify**:
`.\venv\Scripts\python.exe -m unittest tests.test_clipboard_authority -q`
-> all new tests pass.

### Step 2: Make one Windows sequence equal one active copy event

Add failing tests to `tests/test_file_paste_clipboard.py` before editing
`ClipboardHandler`.

The tests must prove:

- startup records the current sequence and never calls the ordinary-content
  callback;
- one active sequence change produces one kind acknowledgement and one payload
  submission, so one Ctrl+C is sufficient;
- repeated identical ordinary content still produces a new active copy event;
- rich-only, screenshot, and empty sequences classify as ordinary;
- an inactive sequence is recorded but publishes neither kind nor content;
- activating or deactivating the handler does not itself publish;
- a clipboard lock leaves the sequence pending instead of consuming it.

Extend `ClipboardHandler` with a small active flag and a per-copy kind callback.
Use `ordinary`/`files` values from the pure authority module or one adjacent
enum; do not create a second wire protocol. Keep ordinary payloads on the
existing latest-wins data sender. Encode an explicit empty marker only when a
real active empty sequence is observed.

Replace content-hash suppression as the definition of a copy event: a changed
Windows sequence on the active screen is the event. Latest-wins scheduling may
collapse queued network payloads, but the local kind acknowledgement occurs
once for every successfully classified sequence.

**Verify**:
`.\venv\Scripts\python.exe -m unittest tests.test_file_paste_clipboard tests.test_clipboard_scheduling -q`
-> all tests pass.

### Step 3: Make local Ctrl+C atomically beat delayed remote data

Add failing injection tests before changing `ClipboardHandler.inject`.

Required cases:

- if the Windows sequence differs from the last processed sequence before a
  remote write, `inject` returns a non-success result and never calls
  `EmptyClipboard`;
- the decisive sequence check occurs after `OpenClipboard`, while the caller
  owns the clipboard lock;
- a successful injection records DeskFlow's new sequence before
  `CloseClipboard` and needs no post-write sleep;
- a local copy immediately after `CloseClipboard` remains a newer pending
  sequence;
- failed validation, decoding, clipboard access, and callbacks always clear
  `is_injecting`.

Do not weaken payload-size checks. Do not retry after detecting a newer local
sequence; that is an authority rejection, not a clipboard-lock failure.

**Verify**:
`.\venv\Scripts\python.exe -m unittest tests.test_file_paste_clipboard -q`
-> all tests pass.

### Step 4: Keep Ctrl+C/Ctrl+V interception bounded and in memory

Add failing tests to `tests/test_file_paste_availability.py` and
`tests/test_file_paste_hotkey.py`.

Extend `PasteCoordinator` with copy-pending state and an injected monotonic
clock or explicit `now` parameter suitable for deterministic tests:

- physical Ctrl+C while Ctrl is held starts a short pending interval and never
  suppresses C;
- Ctrl+V during that interval remains native even if the previous status was
  files;
- confirming ordinary disables file interception;
- confirming files restores/enables file interception;
- an unconfirmed interval expires to the preceding file state;
- reset clears pressed keys, pending state, and file interception;
- repeated C/V keydown events remain idempotent.

Map `VK_C` in `WindowsPasteHotkeyMonitor`. Tests must prove that injected C and
V events remain ignored and that the hook invokes only coordinator methods.
Production hook code must not import `win32clipboard`, `time.sleep`, or network
objects.

**Verify**:
`.\venv\Scripts\python.exe -m unittest tests.test_file_paste_availability tests.test_file_paste_hotkey -q`
-> all tests pass.

### Step 5: Wire active-screen authority through both peers

Add failing routing tests before editing `app/client.py` or `app/server.py`.

Wire these transitions:

- server local screen active: `switching_to_client=False`;
- client local screen active: `is_active=True`;
- set handler activity at connection/start and on both screen-switch paths;
- a classified active local copy claims local authority before scheduling
  content or status;
- the local kind acknowledgement confirms the coordinator and sends the
  existing boolean `file_clipboard_available` message for every valid copy,
  even when the boolean matches the previous value;
- a received status claims remote authority and confirms the coordinator only
  on the physical hook that currently routes DeskFlow input;
- `on_remote_copy` checks authority first, then calls guarded injection, and
  marks remote authority only for an accepted payload;
- disconnect resets authority, activity, copy-pending state, and stale
  availability without sending ordinary startup content on reconnect.

Do not add `clipboard_offer`, payload revisions, cross-lane buffering, or
synchronous clipboard refresh from Ctrl+V.

Test at least these sequences on both server and client routing fakes:

1. server copy -> switch to client -> remote paste;
2. client copy -> switch back -> server paste;
3. local active copy -> delayed remote payload is rejected;
4. unprocessed local sequence -> delayed remote payload is rejected;
5. inactive physical clipboard change is ignored;
6. file -> one Ctrl+C ordinary -> immediate Ctrl+V stays native;
7. reconnect seeds state without ordinary content exchange.

**Verify**:
`.\venv\Scripts\python.exe -m unittest tests.test_file_paste_routing tests.test_clipboard_scheduling -q`
-> all tests pass.

### Step 6: Run the complete regression gate and update the handoff

Run compilation, focused tests, file tests, the full suite, patch integrity,
and a static rejected-approach search. Update the focused handoff with the
confirmed root causes, final symbols, exact test counts, commit status, and the
single-press two-PC checklist. Mark the earlier split-lane handoff section as
superseded rather than deleting its history.

Static search:

`rg -n "clipboard_offer|refresh_before_paste|IDataObjectAsyncCapability|EndOperation|StartOperation|comtypes" app`

Expected: no clipboard-offer or synchronous-refresh architecture; no rejected
asynchronous COM proxy. Any legitimate unrelated match must be explained in
the handoff.

**Verify**:

1. `.\venv\Scripts\python.exe -m compileall -q app tests run.py` -> exit 0.
2. focused clipboard command -> `OK`.
3. file subsystem command -> `OK`.
4. full suite command -> `OK`.
5. `git diff --check` -> exit 0 with no output.

## Test plan

- New pure-state tests: `tests/test_clipboard_authority.py`.
- Windows sequence, active/inactive, empty/rich/repeated, and injection-race
  tests: `tests/test_file_paste_clipboard.py`.
- Copy-pending behavior: `tests/test_file_paste_availability.py`.
- Physical versus injected key filtering: `tests/test_file_paste_hotkey.py`.
- Server/client active-screen and delayed-payload routing:
  `tests/test_file_paste_routing.py`.
- Latest-wins payload compatibility and reconnect lifecycle:
  `tests/test_clipboard_scheduling.py`.
- Existing file and full suites remain mandatory because clipboard authority
  controls file-paste routing.

## Done criteria

- [x] One Ctrl+C creates exactly one acknowledged active copy event in tests.
- [x] Same-machine Ctrl+V executes no clipboard or network work in the hook.
- [x] Newer local content survives delayed remote data before and after polling.
- [x] Inactive physical clipboard changes never become authoritative.
- [x] Startup and reconnect send no ordinary clipboard content.
- [x] File-to-ordinary and ordinary-to-file transitions route correctly.
- [x] Focused, file, and full suites pass (`300` tests on 2026-07-20).
- [x] Compilation and `git diff --check` pass.
- [x] Static search finds none of the rejected architectures.
- [x] Only in-scope source, test, plan, design, and handoff files changed.
- [x] Physical validation remains pending and FIFO remains unimplemented.

## STOP conditions

Stop and write a handback if:

- live in-scope code differs from revision `d731b83` before execution;
- one Ctrl+C cannot be represented as one Windows sequence change in the
  existing polling abstraction;
- accepting the active-screen rule requires raw-input hooks, COM proxies, or a
  second content/status correlation protocol;
- a production keyboard-hook callback must access the clipboard or network;
- authority requires clipboard content, full paths, or synchronized clocks;
- a focused verification fails twice after one reasonable correction;
- the work needs manifest, sender, receiver, queue, or virtual-file COM edits.

The handback must state the observed code/runtime evidence, the required
outcome, and the unresolved design question without choosing a new design.

## Maintenance notes

`ClipboardAuthority` must remain pure state. `ClipboardHandler` owns Windows
sequence and locking rules. `PasteCoordinator` owns only key/interception
state. Client/server route events between those units. Preserve these
boundaries when replacing polling later.

True file FIFO remains the next feature only after both computers run the same
post-repair commit and pass the physical checklist.
