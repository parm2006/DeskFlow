# Clipboard Reliability Phase 1 Design

## Goal

Prevent bursts of clipboard changes—especially rapid screenshots—from building an unbounded queue of expensive compression and network work. Preserve DeskFlow's existing clipboard behavior and wire format.

## Confirmed scope

This phase introduces bounded latest-wins scheduling for outbound clipboard snapshots:

- At most one snapshot is actively being sent.
- At most one newer snapshot waits in a replaceable pending slot.
- If A is active and B, C, then D arrive, A completes and D is sent; B and C are discarded.
- A TCP frame that has started sending is never interrupted.
- Clipboard observation remains responsive while compression and sending happen off the polling thread.

The existing payload keys and codecs remain compatible: `text`, `image`, `html`, and `rtf`, with the existing `clipboard_sync` message type. This phase does not add message IDs, acknowledgements, a new protocol version, retransmission, or format changes.

## Components

`LatestWinsSender` owns a daemon worker and a condition-protected pending slot. `submit(payload)` takes a shallow snapshot so callers can safely reuse their dictionary. The worker removes the newest pending snapshot, sends it to completion, then checks for the latest replacement. `stop()` rejects new submissions, drops pending work, wakes the worker, and joins it with a bounded timeout.

Each `DeskFlowClient` and `DeskFlowServer` owns one sender for its outbound clipboard data channel. Their clipboard callbacks submit a fresh message through that sender rather than performing compression/network work inline. Disconnect/stop shuts the sender down without changing the current wire schema.

## Data flow

1. `ClipboardHandler` notices a new Windows clipboard sequence.
2. It captures the available raw clipboard formats quickly.
3. It submits a raw immutable snapshot to the peer's latest-wins sender.
4. The sender's worker performs format encoding/compression and calls `data_network.send_message()` for the complete message.
5. Changes arriving during step 4 replace the single pending snapshot.

To make observation independent from compression, clipboard capture and payload encoding must be separate operations. Windows clipboard access stays on the polling thread and is released before any compression begins.

## Failure behavior

- A send failure follows the existing network disconnect path.
- Exceptions from one scheduled send are logged and do not leave the sender permanently marked busy.
- Once stopped, the sender refuses submissions and does not send pending work.
- Receiving and clipboard injection are unchanged in this phase.

## Testing

Automated tests must prove:

- A active followed by B, C, and D sends only A then D.
- Submitted dictionaries are snapshotted rather than retained by reference.
- A stopped sender rejects new work and drops pending work.
- Send exceptions do not deadlock `wait_until_idle()`.
- Client and server clipboard callbacks use their sender and preserve the existing `clipboard_sync` payload.
- Text, image, HTML, and RTF encoding produces the same schema and decodable content as before.

The final two-machine check should repeat rapid screenshots while collecting logs from both peers. The check should also cover ordinary text, a single image, HTML, and RTF copy/paste in both directions.

## Success criteria

1. The automated latest-wins and integration tests pass.
2. Outbound clipboard work is bounded to one active plus one pending snapshot.
3. Clipboard polling does not perform compression or network sending inline.
4. Existing text/image/HTML/RTF payload compatibility is preserved.
5. Rapid screenshots no longer make paste unavailable in the two-machine manual test.

## Deferred work

Protocol acknowledgements, message IDs, frame-size limits, TLS identity verification, clipboard preservation on disconnect, richer deduplication, and general repository cleanup remain separate reliability/security slices. The observed `[WinError 10054]` is not attributed to clipboard backpressure without logs from both machines.
