# Security revamp validation

This is the release gate for `fix/security-revamp`. Do not begin background or
daemon work until every two-PC row passes or an explained failure is fixed and
retested.

## Automated evidence

Run from the repository root:

```powershell
.\venv\Scripts\python.exe -m compileall -q app tests
.\venv\Scripts\python.exe -m unittest discover -s tests -q
git diff --check
```

The suite directly covers:

- encrypted PEM identity generation, legacy migration, corruption quarantine,
  DPAPI-protected trust, delayed pin commit, decline, wrong password, changed
  identity, explicit re-pair, and typed connection phases;
- bounded and non-blocking TLS/authentication, stale-socket generations, one
  logical control/data/file session, token purpose, expiry, replay, and session
  mixing;
- AES-256-GCM partial and completed caches, randomized cache names, tamper
  rejection, startup cleanup, cross-record reads, and prefix-independent record
  lookup;
- cancellation from either protocol endpoint, duplicate requests, late chunks
  and completion frames, cancellation during verification, and a successful
  immediately following job;
- error-boundary redaction: typed DeskFlow failures retain safe actionable text,
  while unknown exceptions and logs expose only stable error categories. A
  regression injects a private Windows path through `PermissionError` and proves
  that neither the path nor raw exception text reaches logs.

Connection-state evidence distinguishes a failed attempt from cleanup:
`NetworkClient` enters `FAILED` and retains its typed `last_error`; an explicit
user/application disconnect then enters `DISCONNECTED` without erasing that
failure. Trust cannot be committed from either state.

The 2026-07-13 local checkpoint transferred 100 MiB through TLS into encrypted
staging at 127.1 MiB/s. A separate staging run measured 163.8 MiB/s encrypted
writes and 412.3 MiB/s authenticated range reads. These are loopback safety
checks, not substitutes for the LAN measurement below.

The real Windows CustomTkinter runtime was also exercised locally. The root was
resizable, and the status/tab width changed from 660 px at a 700 px window to
310 px at a 350 px window. The read-only status used word wrapping and allowed
text selection. The client-only pairing modal ran as a separate grabbed
top-level, centered over DeskFlow, displayed the short code and selectable full
fingerprint, adapted its wrapping at the 360 x 320 minimum modal size, kept both
actions visible, recorded approval, released its grab, and closed. Automated
tests also cover decline, timeout, application shutdown, late decisions, and a
root-destruction scheduling race. This validates local widget behavior but does
not replace visual confirmation on both target PCs.

## Two-PC prerequisites

1. On both PCs, check out the same `fix/security-revamp` commit and confirm
   `git status --short` is empty.
2. Record the environment on **both computers**, keeping the outputs labelled
   `SERVER` and `CLIENT`.

   On the **server computer**, open PowerShell in any directory and run:

   ```powershell
   Get-CimInstance Win32_OperatingSystem |
       Select-Object Caption, Version, BuildNumber

   Get-NetAdapter |
       Where-Object Status -eq "Up" |
       Select-Object Name, MediaType, PhysicalMediaType, LinkSpeed, InterfaceDescription
   ```

   If the active server adapter is Wi-Fi, also run:

   ```powershell
   netsh wlan show interfaces
   ```

   On the **client computer**, run the same commands:

   ```powershell
   Get-CimInstance Win32_OperatingSystem |
       Select-Object Caption, Version, BuildNumber

   Get-NetAdapter |
       Where-Object Status -eq "Up" |
       Select-Object Name, MediaType, PhysicalMediaType, LinkSpeed, InterfaceDescription
   ```

   If the active client adapter is Wi-Fi, also run:

   ```powershell
   netsh wlan show interfaces
   ```

   Record `Caption`, `Version`, `BuildNumber`, the active adapter name and
   description, whether it is Wi-Fi or Ethernet, and `LinkSpeed`. For Wi-Fi,
   also record `Band`, `Radio type`, `Receive rate (Mbps)`, `Transmit rate
   (Mbps)`, and `Signal` from the connected primary interface. Ignore any
   disconnected secondary Wi-Fi interface. For Ethernet, skip `netsh` and use
   the active adapter's `LinkSpeed`.
3. Start each copy with `run.bat`. Do not start any background/daemon prototype.

### Recorded target environment (2026-07-13)

| Role | Windows | IPv4 | Connection | Adapter | Reported rates | Signal |
|---|---|---|---|---|---|---|
| Server | Redacted Windows environment | 192.0.2.10 | 5 GHz 802.11ac Wi-Fi | Redacted adapter | Redacted rates | 99% |
| Client | Redacted Windows environment | 192.0.2.11 | 5 GHz 802.11ac Wi-Fi | Redacted adapter | Redacted rates | 82% |

The historical network baseline was redacted.

## Two-PC acceptance matrix

Record PASS/FAIL, observed speed or latency where requested, and a concise note.

### Validation checkpoint: 2026-07-13

Testing stopped after repeat-transfer and remote-input failures. Rows 1-6 passed
on the client-to-server pairing path and do not need to be repeated unless a
later fix changes pairing, trust, or authentication. A large transfer completed
at the restored speed, and cancellation updated both DeskFlow windows and the
transfer toast. A later transfer remained at `Waiting for Windows Explorer`
until it was cancelled. Delete did not affect the selected remote file.

The client also failed to reconnect once without an error, then connected after
DeskFlow was relaunched. Treat reconnect as failed until it works repeatedly
without restarting either application. The unchanged pairing code after
forgetting trust is expected because the server identity did not change; the
fresh comparison and approval in row 6 passed.

| # | Test | Required result | Server → client | Client → server | Notes |
|---:|---|---|---|---|---|
| 1 | First pairing | Same short code on both PCs; full client fingerprint is selectable; no duplicate code | PASS | N/A | Pairing UI and comparison passed. |
| 2 | Decline then retry | Decline saves no pin; next attempt asks again and can connect | PASS | N/A | Retry prompted and connected. |
| 3 | Wrong password then correct password | Wrong password saves no pin and does not poison the next connection | PASS | N/A | Authentication recovered on the next attempt. Error wording still needs improvement. |
| 4 | Saved pairing reconnect | Reconnect succeeds without another approval prompt | PASS | N/A | Saved pairing reconnect passed during the first six tests. |
| 5 | Changed server identity | Connection stops with inline identity-changed guidance; it never silently replaces the pin | PASS | N/A | Changed identity was rejected. |
| 6 | Inline re-pair | Forget/re-pair requires a fresh code comparison, then connects | PASS | N/A | Fresh approval succeeded. The code correctly stayed the same for the unchanged server identity. |
| 7 | 100 MiB copy | Hash and size match; record elapsed seconds and MiB/s; no major regression from the same-machine `main` baseline | PARTIAL | NOT TESTED | Transfer speed was restored, but elapsed time, MiB/s, size, and hash still need recording. A later transfer stalled before Explorer consumed it. |
| 8 | Control latency under copy | Mouse remains smooth; typing, Delete, clicks, and scrolling arrive without visible stalls | FAIL | NOT TESTED | Delete did not delete a selected remote file. Other inputs and latency still need explicit checks. |
| 9 | Clipboard under copy | Plain text and a screenshot can be copied and pasted while the 100 MiB file is moving | NOT TESTED | NOT TESTED | Resume after the transfer lifecycle is fixed. |
| 10 | Cancel at source | Both toasts enter cancelled and disappear; no later offset/hash error | PARTIAL | NOT TESTED | Cancellation synchronized between the windows and toast; direction and post-cancel health still need confirmation. |
| 11 | Cancel at destination | Both toasts enter cancelled and disappear; no cancellation echo | PARTIAL | NOT TESTED | Cancellation synchronized between the windows and toast; direction and post-cancel health still need confirmation. |
| 12 | Immediate next transfer | A small file succeeds immediately after each cancellation without reconnecting | NOT TESTED | NOT TESTED | The stalled second transfer was cancelled, but no third transfer was reported afterward. Test this after the repeat-transfer stall is fixed. |
| 13 | Disconnect/reconnect | Network loss clears the session and encrypted caches; reconnect creates a fresh usable session | FAIL | NOT TESTED | One reconnect silently failed and worked only after relaunching DeskFlow. Repeated reconnect testing remains. |
| 14 | GUI resize and error copy | Long inline errors wrap at narrow and wide sizes and can be selected/copied; no extra error popup | NOT TESTED | N/A | Screenshots show excess empty space. Requested behavior changed to a compact, fixed-size, non-maximizable window. |

### Unresolved observations before resuming the matrix

1. Replace generic socket/authentication text with safe, actionable messages,
   including an explicit incorrect-password message.
2. Persist the last successfully used Server or Client role and select that tab
   when DeskFlow next starts. Do not save a role after a failed start or failed
   connection.
3. Place the cursor visually at the adjoining monitor edge. The current 96 px
   entry inset is too large; retain only enough inset to prevent an immediate
   switch-back.
4. Reproduce the silent reconnect failure and make every failed attempt finish
   with an actionable inline error.
5. Reproduce the second-paste `Waiting for Windows Explorer` stall. Verify that
   the virtual clipboard owner, paste injection worker, and transfer lifecycle
   reset cleanly after success and cancellation.
6. Restore Delete forwarding for a selected file on the controlled computer
   without breaking ordinary typing or Ctrl+V interception.
7. Redesign the root window to use its compact content size, disable resizing,
   and disable maximizing. Long status text must still wrap and remain
   selectable inside the fixed window.

After these items are fixed and both PCs use the same new testing commit, resume
with rows 7-14. Recheck only any of rows 1-6 whose pairing, trust, or
authentication implementation changed.

## Changed-identity test without deleting the real identity

Stop the normal server. In a new PowerShell window on the server, launch one
temporary identity by changing `LOCALAPPDATA` only for that process:

```powershell
$env:LOCALAPPDATA = Join-Path $env:TEMP "DeskFlow-identity-validation"
.\venv\Scripts\python.exe run.py
```

The client must reject it as an identity change. Close the temporary server and
restart normally before testing the inline re-pair action. Removing the temporary
directory afterward is optional; never delete the normal DeskFlow identity to
perform this test.

## Completion record

- Commit tested on PC 1:
- Commit tested on PC 2:
- `main` 100 MiB baseline on the same link:
- Security-revamp 100 MiB result on the same link:
- Unexplained failures: repeat transfer stuck waiting for Explorer; Delete not
  forwarded; one silent reconnect required an application relaunch
- Tested by:
- Date:

Only after all rows pass and the completion record is filled may Plan 004 and
the security-revamp goal be marked complete.
