# Plan 005: Replace embedded pairing approval with a client modal

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on.
> If anything in "STOP conditions" occurs, stop and write a handback;
> do not improvise. When done, update this plan's status row in the
> effort README.
>
> **Drift check (run first)**:
> `git diff 4ec24e4 -- app/gui.py app/pairing_dialog.py tests/test_pairing_dialog.py tests/test_security_network.py docs/plans/security-revamp/VALIDATION.md`
> If an in-scope file has changed since this plan was written, compare the
> current-state excerpts against the live code before proceeding. Treat a
> mismatch in pairing behavior or ownership as a STOP condition.

## Status

- **Effort**: M
- **Risk**: MED
- **Depends on**: 004-security-ui-and-system-verification.md
- **Planned at**: revision `4ec24e4`, 2026-07-13
- **Design**: `docs/superpowers/specs/2026-07-13-client-pairing-modal-design.md`
- **Execution**: AUTOMATED COMPLETE; TWO-PC PENDING

## Why this matters

The embedded client pairing panel can be missed during connection and previously
made a bounded wait look like a hung connection. First-pair approval is a
security decision, so DeskFlow must put the decision in a visible client-owned
modal without changing server behavior or saving trust early. This is the final
security code change before the two-PC validation matrix starts from the
beginning.

## Current state

- `app/gui.py:97-151` builds the client form and an embedded `pairing_frame`
  inside the client tab.
- `app/gui.py:233-264` constructs `DeskFlowClient` with
  `fingerprint_approval=self._approve_fingerprint`; this is the existing UI
  boundary and must remain client-owned.
- `app/gui.py:306-355` waits up to 60 seconds, places the embedded frame over
  the client tab, and maps approval to `True`, decline to `False`, and expiry to
  `PairingTimeout`.
- `app/gui.py:384-391` disconnects and destroys the root on shutdown but does
  not explicitly complete an active pairing decision.
- `app/network.py:507-527` runs the approval callback in a bounded worker and
  preserves callback exceptions. Its bool-or-typed-exception contract already
  supports this change and should not be redesigned.
- `app/file_transfer/toast.py:52-76` is the local `CTkToplevel` construction
  exemplar. Follow its ownership pattern, but use a normal decorated modal
  rather than an overrideredirect topmost toast.
- `tests/test_security_network.py:38-71` is the typed approval deadline and
  exception-propagation exemplar. Preserve these tests.
- `tests/test_file_transfer_toast.py:7-65` is the lightweight view/controller
  test exemplar. Prefer observable state transitions over CustomTkinter
  internals.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Focused dialog tests | `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_pairing_dialog.py" -v` | all new tests pass |
| Network approval regression | `.\venv\Scripts\python.exe -m unittest tests.test_security_network -v` | existing typed deadline and trust tests pass |
| Compile | `.\venv\Scripts\python.exe -m compileall -q app tests` | exit 0, no output |
| Full suite | `.\venv\Scripts\python.exe -m unittest discover -s tests -q` | all tests pass |
| Whitespace | `git diff --check` | exit 0, no output |
| Scope | `git status --short` | only in-scope files are listed |

## Scope

**In scope** (the only implementation and verification files to modify):

- `app/pairing_dialog.py` (new) - client modal and one-shot decision ownership.
- `app/gui.py` - remove the embedded panel and connect the modal to the existing
  approval callback and shutdown path.
- `tests/test_pairing_dialog.py` (new) - decision, modal-controller, integration,
  and Windows Tk runtime coverage.
- `tests/test_security_network.py` - only if an existing approval integration
  assertion needs to express the same typed outcome more precisely.
- `docs/plans/security-revamp/VALIDATION.md` - replace obsolete embedded-panel
  evidence with modal evidence after the runtime check passes.
- `docs/plans/security-revamp/README.md` and this plan - execution status only.

**Out of scope** (do not touch):

- `app/network.py`, `app/client.py`, `app/server.py`, `app/crypto.py`, and
  `app/trust.py` - the approval, delayed-trust, and server-code contracts already
  support the modal.
- `app/file_transfer/**` - transfer performance and cancellation behavior do not
  depend on this view change.
- Background, daemon, hide/show, synchronized exit, packaging, and shortcut code.
- Any implementation or history from the abandoned prototype branches.

## Steps

### Step 1: Specify one-shot pairing decisions with failing tests

Create `tests/test_pairing_dialog.py`. Describe the desired public behavior
before creating production code:

- approval completes once and yields an approved outcome;
- button decline, window close, and Escape yield the same declined outcome;
- timeout yields a distinct timed-out outcome;
- application shutdown yields a distinct closed outcome and releases a waiting
  callback;
- a late click, timeout, close, or shutdown cannot replace the first outcome;
- presentation data contains the short code, canonical server address, full
  fingerprint, wrapped/selectable details, and both action labels.

Keep the decision primitive independent of Tk so race behavior can use real
threads and events. If a thin presentation model makes widget tests clearer,
keep it immutable and limited to text and layout facts required by the design.

**Verify RED**:
`.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_pairing_dialog.py" -v`
must fail because `app.pairing_dialog` or its required behavior does not exist.
An import typo or unrelated error does not count as the required failure.

### Step 2: Implement the isolated modal and decision owner

Create `app/pairing_dialog.py` with two clear responsibilities:

1. A thread-safe, one-shot decision owner exposes bounded waiting and idempotent
   completion for approved, declined, timed out, and application-closed outcomes.
2. A `CTkToplevel` controller renders the client-only security prompt and maps
   **Codes match**, **Decline**, `WM_DELETE_WINDOW`, and Escape into that owner.

The window must be transient to the DeskFlow root, acquire a grab while open,
center after measuring its requested size, keep a reasonable minimum size, wrap
long content, and put the fingerprint in a disabled-but-selectable textbox.
All widget calls occur on the Tk thread. Cleanup must safely release the grab
and destroy the window once, including when timeout and user input race.

Do not use `tkinter.messagebox`, require a server-side click, or save trust.

**Verify GREEN**:
`.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_pairing_dialog.py" -v`
must pass the decision and presentation tests added in Step 1.

### Step 3: Specify and integrate the client callback with failing tests

Add integration cases to `tests/test_pairing_dialog.py` around
`DeskFlowGUI._approve_fingerprint` and shutdown. Use a small fake root/scheduler
or an injected dialog factory where a real Tk window is not needed. The cases
must prove:

- the network worker schedules modal creation onto Tk's thread;
- approved maps to `True` and declined maps to `False`;
- timeout raises `PairingTimeout` with explicit reconnect/compare guidance;
- application shutdown releases the waiting callback and leaves no active modal;
- closing or timing out cannot be followed by a late approval;
- the old `pairing_frame`, embedded controls, and place/pack cleanup path are no
  longer constructed or referenced.

**Verify RED**:
`.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_pairing_dialog.py" -v`
must fail against the current embedded implementation for the expected modal
integration reason.

Update `app/gui.py` minimally:

- remove embedded pairing widgets and their show/hide methods;
- keep `fingerprint_approval=self._approve_fingerprint` as the client boundary;
- let `_approve_fingerprint` own one current decision, schedule modal creation,
  wait for the bounded result, and translate it to the network contract;
- close any active modal and complete its decision before `destroy()` in
  `on_close`;
- keep approval progress and all terminal errors in the selectable main status
  area.

The server tab remains unchanged and continues to display its comparison code
without a confirmation action.

**Verify GREEN**:

1. `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_pairing_dialog.py" -v`
   -> all dialog and GUI-integration tests pass.
2. `.\venv\Scripts\python.exe -m unittest tests.test_security_network -v`
   -> all approval deadline, delayed trust, decline, reconnect, and changed
   identity tests pass.

### Step 4: Exercise a real Windows Tk lifecycle

Add a Windows runtime case in `tests/test_pairing_dialog.py` that creates an
actual CustomTkinter root and modal, calls `update_idletasks`, and asserts:

- the modal is a separate mapped top-level owned by the client root;
- its grab is active while it is open;
- its measured rectangle is centered over the root and remains on screen;
- the details textbox wraps words, remains read-only, and permits selection;
- both buttons fit inside the modal at DeskFlow's `330x560` minimum root size;
- approve, decline, close, Escape, timeout, and root shutdown each destroy the
  modal and release the grab.

The test must always destroy its root in `finally`. It may skip only when Tk
cannot initialize; it must run, not skip, on the target Windows development
machine.

**Verify**:
`.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_pairing_dialog.py" -v`
must pass with the Windows runtime case reported as `ok`, not `skipped`.

Update `docs/plans/security-revamp/VALIDATION.md` with the new local runtime
evidence and remove the statement that the embedded panel was the current
validated interaction. Do not mark any two-PC row passed.

### Step 5: Freeze the testing candidate

Run the complete local gate without modifying behavior after it passes:

```powershell
.\venv\Scripts\python.exe -m compileall -q app tests
.\venv\Scripts\python.exe -m unittest discover -s tests -q
git diff --check
git status --short
```

Expected: compile and whitespace checks emit no errors; the full suite passes;
status lists only this plan's in-scope files. Review the exact diff, update the
README row and this plan's status to `AUTOMATED COMPLETE; TWO-PC PENDING`, and
create a commit whose subject starts with `testing:`. Do not label the modal
functional or complete until the two-PC matrix passes.

After that commit is present on both computers, run
`docs/plans/security-revamp/VALIDATION.md` from row 1. Do not reuse earlier
partial first-pair results.

## Test plan

- New tests live in `tests/test_pairing_dialog.py` and cover the one-shot
  outcome model, every close path, races, GUI integration, layout facts, and an
  actual Windows Tk lifecycle.
- Preserve `tests/test_security_network.py` as the network/trust regression
  suite; do not replace real TLS session tests with mocks.
- Follow `tests/test_file_transfer_toast.py` for small view assertions and
  `tests/test_security_network.py:74-244` for real security integration.
- **Verify**:
  `.\venv\Scripts\python.exe -m unittest discover -s tests -q` -> the entire
  suite, including all new tests, passes.

## Done criteria

- [ ] The client alone opens a separate pairing modal for an unknown identity.
- [ ] Approve, decline, close, Escape, timeout, and shutdown have one typed,
      terminal outcome and cannot race into a second outcome.
- [ ] The server remains display-only for pairing and known identities reconnect
      without a prompt.
- [ ] Trust is still committed only after password authentication and secondary
      lane binding.
- [ ] The actual Windows Tk runtime test passes without skipping.
- [ ] `.\venv\Scripts\python.exe -m compileall -q app tests` exits 0.
- [ ] `.\venv\Scripts\python.exe -m unittest discover -s tests -q` passes.
- [ ] `git diff --check` exits 0 with no output.
- [ ] No file outside the in-scope list is modified.
- [ ] The checkpoint commit begins with `testing:` and no two-PC validation row
      is marked passed prematurely.

## STOP conditions

Stop and write a handback if:

- the live approval callback no longer returns bool or raises a typed exception;
- the modal appears to require any server-side confirmation or protocol change;
- safe shutdown requires changing `app/network.py`, `app/client.py`, or server
  behavior rather than completing the active UI decision before destroy;
- Tk cannot provide both modal ownership and a selectable read-only fingerprint
  without platform-specific native code;
- the actual Windows Tk runtime case skips or cannot release its grab/window;
- any test step fails twice after one focused correction;
- implementation requires touching file transfer, daemon, background, packaging,
  or shortcut code;
- a design fork appears that the approved specification does not resolve.

The handback must state current behavior, desired behavior, evidence gathered,
and the unresolved question without choosing a new design.

## Maintenance notes

Pairing UI changes must preserve the client-only approval boundary and delayed
trust commit. Future background-mode work must decide how to surface this modal
when the main window is hidden; that decision is deliberately deferred until
the security matrix passes. Reviewers should scrutinize Tk-thread ownership,
grab release, shutdown races, and any path that could save trust after a
non-approved outcome.
