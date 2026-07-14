# DeskFlow client pairing modal

## Purpose and scope

Replace the client's embedded first-pair approval panel with a separate DeskFlow-owned modal window. This is the final scoped security change before the two-computer validation matrix begins. The server continues to display its pairing code in the main window and requires no confirmation click. Background and daemon behavior remain out of scope.

## Interaction

DeskFlow opens the modal only when the client connects to a server whose identity is not yet trusted. The modal stays centered over the client window and blocks interaction with that window until the user decides or the deadline expires. It uses DeskFlow's existing visual style rather than a generic operating-system message box.

The modal displays:

- a prominent short comparison code;
- the server's canonical address;
- the complete certificate fingerprint in a wrapped, read-only, selectable text area;
- a warning to approve only when the short code matches the code shown on the server;
- **Codes match** and **Decline** buttons.

The layout must keep all information and actions visible at DeskFlow's minimum supported window and display sizes. Long text wraps instead of widening the window or being clipped.

## Decisions and terminal outcomes

**Codes match** records an approval decision and allows authentication to continue. Approval alone does not save trust. DeskFlow saves the server identity only after password authentication and all secondary network lanes bind successfully.

**Decline**, the window close button, and Escape all produce the same explicit decline result. They save no trust and return a clear declined status to the main window. If the user makes no choice within 60 seconds, DeskFlow closes the modal, saves no trust, and reports that pairing approval timed out. A decision received after completion has no effect.

Closing DeskFlow while the modal is open must release the waiting connection attempt without leaving a pairing worker or modal window alive.

## Threading and ownership

The Tk main thread creates, updates, and destroys the modal. The network approval callback waits on one bounded decision object and receives one typed result: approved, declined, timed out, or application closed. Cleanup is idempotent so simultaneous timeout, shutdown, and user input cannot complete the decision twice.

The client owns the approval interaction. The server only supplies and displays comparison information. Existing trusted connections do not open the modal. A changed server identity remains a hard failure and directs the user to **Forget saved identity and re-pair** rather than offering approval inline.

## Error presentation

The modal is an intentional security prompt, not an error dialog. Connection, timeout, authentication, and identity-change errors remain wrapped, selectable, and copyable in the main DeskFlow status area. DeskFlow creates no additional error popup.

## Verification gate

Automated tests must first fail against the embedded-panel implementation and then cover:

- client-only modal creation for an unknown identity;
- approve, decline, close-button, Escape, timeout, and application-shutdown outcomes;
- one terminal decision when timeout and user input race;
- no trust saved before full connection success;
- no modal for a saved matching identity;
- changed identity rejected through the re-pair path;
- modal geometry and wrapped/selectable details at the minimum supported size.

A local Tk runtime check must confirm that the modal is centered, remains above DeskFlow, blocks the client window, exposes both actions, and closes for every terminal outcome.

After the testing-labeled commit is available on both computers, freeze security code and run `docs/plans/security-revamp/VALIDATION.md` from the beginning. Earlier partial results do not count because the first-pair interaction changed.
