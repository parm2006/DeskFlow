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

## When to run this plan

Do not continue two-PC testing on commit `4b831fa`. Wait for a new `testing:`
commit that addresses the failures in `VALIDATION-RESULTS.md`. Then run this
procedure in order. Stop at the first failure, record the exact status text and
which step failed, and do not continue with dependent steps.

## Test 1: synchronize and verify both copies

On the server computer:

```powershell
git switch fix/security-revamp
git pull --ff-only
git rev-parse --short HEAD
git status --short
.\venv\Scripts\python.exe -m compileall -q app tests
.\venv\Scripts\python.exe -m unittest discover -s tests -q
git diff --check
```

Run the same commands on the client computer. Both computers must report the
same commit. `git status --short` and `git diff --check` must print nothing, and
the Python test suite must pass.

## Test 2: compact window and saved role

1. Start DeskFlow on the server computer. Confirm the window opens at a compact
   fixed size with no large unused region.
2. Try to drag each window edge and double-click the title bar. The window must
   neither resize nor maximize.
3. Start the server successfully, close DeskFlow, and reopen it. The Server tab
   must be selected.
4. On the client computer, connect successfully, close DeskFlow, and reopen it.
   The Client tab must be selected.
5. Cause one failed client connection, close DeskFlow, and reopen it. The saved
   role must still be the role from the last successful start or connection.

## Test 3: actionable connection errors

Run each case on the client and copy the complete red status text into the
results file.

1. Start the server with password `deskflow-test-good`.
2. Connect with `deskflow-test-wrong`. The message must say that the password is
   incorrect and tell the user to check the server password. It must not expose
   a traceback, path, token, or certificate secret.
3. Connect with the correct password. It must succeed without clearing pairing
   data or relaunching either application.
4. Stop the server and try to connect. The message must say that DeskFlow could
   not reach the server and suggest checking its address, port, and running
   state.
5. Enter an unreachable address and connect. The attempt must end automatically
   within the documented timeout and show an actionable message.

## Test 4: reconnect, layout changes, and cursor entry

For each client position—right, left, top, and bottom—perform these steps:

1. Select the position on the server before starting it.
2. Connect the client without relaunching either application.
3. Cross from the server to the client. The cursor must appear visually at the
   adjoining edge, with only a tiny safety inset, and must not switch straight
   back by itself.
4. Move back to the server and confirm the cursor appears at the corresponding
   server edge.
5. Disconnect and reconnect without closing DeskFlow. No attempt may hang or
   fail silently.

After all four positions, repeat disconnect and reconnect three more times on
the final position. Every attempt must either connect or show an actionable
error within its timeout.

## Test 5: Delete followed by a second transfer

Use disposable files only.

1. Create `delete-me.txt`, `first-copy.txt`, and `second-copy.txt` on the client
   desktop.
2. While controlling the client from the server, select `delete-me.txt` and
   press Delete on the server keyboard. Confirm the file leaves the desktop.
3. Copy `first-copy.txt` from the client to the server. Wait for completion and
   for both transfer toasts to close.
4. Wait ten seconds. Copy `second-copy.txt` in the same direction without
   reconnecting. It must complete and must not remain at `Waiting for Windows
   Explorer`.
5. Repeat steps 3-4 from server to client.
6. Repeat the original observed sequence: complete one transfer, wait, delete a
   different selected remote file, and complete another transfer. This isolates
   whether Delete affects the subsequent paste lifecycle.

## Test 6: measured 100 MiB transfer in both directions

Create a new random test file on the source computer:

```powershell
$path = Join-Path $env:USERPROFILE "Desktop\DeskFlow-100MiB.bin"
$buffer = [byte[]]::new(1MB)
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$stream = [IO.File]::Create($path)
1..100 | ForEach-Object {
    $rng.GetBytes($buffer)
    $stream.Write($buffer, 0, $buffer.Length)
}
$stream.Dispose()
$rng.Dispose()
Get-Item $path | Select-Object FullName, Length
Get-FileHash $path -Algorithm SHA256
```

Immediately before initiating the paste, run:

```powershell
$timer = [Diagnostics.Stopwatch]::StartNew()
```

Immediately after DeskFlow reports completion, run:

```powershell
$timer.Stop()
$seconds = $timer.Elapsed.TotalSeconds
$mibPerSecond = 100 / $seconds
[pscustomobject]@{ Seconds = $seconds; MiBPerSecond = $mibPerSecond }
```

On the destination, run `Get-Item` and `Get-FileHash` against the received file.
The source and destination lengths and SHA-256 hashes must match. Record seconds
and MiB/s. Repeat once from server to client and once from client to server.

## Test 7: input and clipboard while 100 MiB is moving

During each direction of Test 6:

1. Move the mouse continuously between visible targets.
2. Type a short sentence in Notepad.
3. Click and scroll.
4. Select a disposable file and press Delete from the controlling keyboard.
5. Copy and paste plain text.
6. Copy and paste a screenshot.

Mouse, typing, Delete, clicks, scrolling, and clipboard updates must remain
usable without visible multi-second stalls.

## Test 8: cancellation and immediate recovery

Run all four cases: server-to-client cancelled at the source, server-to-client
cancelled at the destination, client-to-server cancelled at the source, and
client-to-server cancelled at the destination.

For each case:

1. Start the 100 MiB transfer and cancel it after progress begins.
2. Confirm both windows and both toasts enter the cancelled state and then
   clear. No offset, hash, or cancellation-echo error may appear.
3. Without reconnecting, transfer a small text file in the same direction. It
   must complete immediately.

## Test 9: network loss and recovery

1. Connect normally, then disable Wi-Fi on the client computer.
2. Both applications must leave the connected state within their timeout and
   clear any active transfer toast.
3. Re-enable Wi-Fi and reconnect without relaunching DeskFlow.
4. Transfer a small file, plain text, and a screenshot to prove the new session
   is usable.
5. Repeat once while a 100 MiB transfer is active.

## Test 10: fixed-window error rendering

Trigger the wrong-password and unreachable-server messages again. Confirm each
message wraps inside the fixed window, remains centered and readable, can be
selected and copied, and does not open a separate error popup.

## Completion record

Add the results to `VALIDATION-RESULTS.md`, including:

- commit tested on both computers;
- PASS or FAIL for Tests 1-10;
- server-to-client and client-to-server seconds and MiB/s;
- source and destination hashes;
- the complete text of any error;
- whether a relaunch or reconnect was required;
- tester and date.

Only after all ten tests pass may Plan 004 and the security-revamp goal be
marked complete or any background/daemon work begin.
