# Security revamp validation results

This file records observations from two-PC testing. Follow `VALIDATION.md` for
the current test procedure.

## 2026-07-13 checkpoint

Tested commit: `4b831fa`

### Environment

| Role | Windows | IPv4 | Connection | Adapter | Reported rates | Signal |
|---|---|---|---|---|---|---|
| Server | Redacted | Redacted | Wi-Fi | Redacted | Redacted | Redacted |
| Client | Redacted | Redacted | Wi-Fi | Redacted | Redacted | Redacted |

The historical network baseline was removed because it identified the tester's
private environment. Future results must use role labels instead of addresses
and omit hardware identifiers.

### Results

| Area | Result | Observation |
|---|---|---|
| First pairing | PASS | The client showed one approval prompt with the comparison code and selectable fingerprint. |
| Decline and retry | PASS | Declining saved no trust; retry prompted again and connected. |
| Wrong then correct password | PASS | The failed password did not poison the next connection. The error text was too generic. |
| Saved pairing reconnect | PASS | A saved pairing reconnected without another approval prompt. |
| Changed server identity | PASS | DeskFlow rejected the changed identity. |
| Forget and re-pair | PASS | Forgetting trust required fresh approval and then connected. The comparison code correctly remained unchanged because the server identity was unchanged. |
| Transfer speed | PARTIAL | A file transfer completed normally and the previous severe speed regression was not observed. Exact size, hash, elapsed time, direction, and MiB/s were not recorded. |
| Cancellation | PARTIAL | Cancelling updated both DeskFlow windows and the transfer toast. Both directions, both cancellation endpoints, and the immediate next transfer were not all tested. |
| Repeat transfer | FAIL | The first transfer completed normally. After waiting, the user attempted to delete a selected remote file and then initiated another copy. The second transfer remained at `Waiting for Windows Explorer` until cancelled. Delete may or may not be related. |
| Remote Delete | FAIL | Pressing Delete on the server did not delete the selected client file. |
| Reconnect | FAIL | One connection attempt produced no error and did not connect. Relaunching DeskFlow allowed it to connect again. |
| Cursor entry | FAIL | The cursor appeared noticeably inside the destination monitor instead of at the adjoining edge. |
| Last successful role | FAIL | Restarting DeskFlow did not reopen the last successfully used Server or Client tab. |
| Main window | CHANGE REQUESTED | The window contained substantial empty space. It should open at a compact fixed size and should not be resizable or maximizable. |

### Code findings associated with this checkpoint

- Cursor entry used a hard-coded 96 px inset.
- The root window used `420x650` and enabled resizing.
- No setting persisted the last successfully used role.
- The virtual-paste worker lacked a per-request timeout and a failure path back
  to the transfer status, so `Waiting for Windows Explorer` could remain
  indefinitely.
- The GUI disconnect callback could act after a newer client object was created;
  this is a candidate explanation for the intermittent reconnect failure and
  requires a regression test.
- Delete passed through the generic special-key path, but no focused Windows
  forwarding regression covered it.

Testing stopped at this checkpoint. Tests that depend on repeat transfers,
Delete, or reliable reconnect were not treated as passed.
