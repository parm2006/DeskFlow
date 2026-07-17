# Security revamp: final two-PC validation

This document is the authoritative release gate for `fix/security-revamp`. Run
every test on the final revision. Do not begin background/daemon work, merge the
branch, or treat the security revamp as complete until every required test
passes.

Record results in [VALIDATION-RESULTS.md](VALIDATION-RESULTS.md). The observations
from commit `4b831fa` are historical evidence only. They do not count toward
this gate.

## Before the tester starts

The code owner must complete these steps first:

1. Commit the current clipboard and network hardening changes.
2. Push `fix/security-revamp`.
3. Give the tester the final short commit SHA.
4. Freeze security code while this matrix runs. If a test fails, add a
   regression test, fix the failure, create another `testing:` commit, and
   restart the affected part of the matrix on the new SHA.

Do not test an uncommitted working tree or continue testing commit `4b831fa`.

## Test rules

- Use two physical Windows PCs on the same LAN.
- Label captured output `SERVER` or `CLIENT`.
- Use disposable files. Never use private documents for failure, cancellation,
  or corruption tests.
- Run the tests in order. Stop at the first failure that makes later tests
  unreliable.
- Copy exact DeskFlow status text into the results file. Preserve relevant logs.
- A relaunch or reconnect counts as a failure unless the test explicitly asks
  for one.
- `Ctrl+Alt+Shift+Escape` must always restore local input on the server.
- Background operation, synchronized hide/show, synchronized full-app exit,
  packaging, and code signing are outside this gate.

## Test 0: synchronize and verify the final revision

Run these commands on the server PC and then the client PC:

```powershell
git switch fix/security-revamp
git pull --ff-only
git rev-parse --short HEAD
git status --short
.\venv\Scripts\python.exe -m compileall -q app tests
.\venv\Scripts\python.exe -m unittest discover -s tests -q
git diff --check
```

Pass criteria:

- Both PCs print the final SHA supplied by the code owner.
- Both PCs print the same SHA.
- `git status --short` prints nothing on both PCs.
- Compilation and the full test suite pass on both PCs.
- `git diff --check` prints nothing on both PCs.

Stop if either checkout is dirty, the SHAs differ, or an automated check fails.

## Test 1: record the environment and idle network baseline

Run on each PC:

```powershell
Get-CimInstance Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber

Get-NetIPConfiguration |
    Where-Object { $_.NetAdapter.Status -eq "Up" -and $_.IPv4DefaultGateway } |
    Select-Object InterfaceAlias, IPv4Address, IPv4DefaultGateway

Get-NetAdapter |
    Where-Object Status -eq "Up" |
    Select-Object Name, MediaType, PhysicalMediaType, LinkSpeed, InterfaceDescription
```

If the active adapter is Wi-Fi, also run:

```powershell
netsh wlan show interfaces
```

On the client, replace `<SERVER_IP>` and run:

```powershell
ping <SERVER_IP> -n 20
```

Record the Windows version/build, IPv4 address, connection type, adapter,
reported link speed, and ping loss/minimum/maximum/average. For Wi-Fi, also
record the band, radio type, receive/transmit rates, and signal. Ignore
disconnected secondary adapters.

## Test 2: verify local identity, pin, and staging protection

Start DeskFlow once on each PC so it creates an identity. Then run on each PC:

```powershell
$identity = Join-Path $env:LOCALAPPDATA "DeskFlow\identity"
$pointer = Get-Content (Join-Path $identity "current.json") | ConvertFrom-Json
$generation = Join-Path (Join-Path $identity "generations") $pointer.generation
Get-Content (Join-Path $generation "key.pem") -TotalCount 1
Get-ChildItem $generation | Select-Object Name, Length
```

Pass criteria:

- The key begins with `-----BEGIN ENCRYPTED PRIVATE KEY-----`.
- The active generation contains `cert.pem`, `key.pem`, and
  `key-password.dpapi`.
- No plaintext temporary key exists in the repository root.

After successful pairing, run on the client:

```powershell
$peers = Join-Path $env:LOCALAPPDATA "DeskFlow\peers"
Get-ChildItem $peers -File | Select-Object Name, Length
Select-String -Path (Join-Path $peers "*") -SimpleMatch "<SERVER_IP>"
```

Pass if the peer filenames are hash-like, the files contain binary protected
data, and `Select-String` does not reveal the server address.

## Test 3: validate pairing and trust lifecycle

Use server password `deskflow-test-good`.

1. Start the server. Confirm it shows one short comparison code and no approval
   popup.
2. On the client, enter the correct password, click **Forget saved identity and
   re-pair**, and connect.
3. Confirm only the client opens a modal. The short code must match the server
   exactly. The full fingerprint must be selectable and copyable. Text must
   wrap, and both actions must fit.
4. Decline. The connection must end with an actionable message, and DeskFlow
   must save no pin.
5. Reconnect and leave the modal untouched. It must close automatically within
   the approval timeout. A retry must prompt again.
6. Enter `deskflow-test-wrong`, reconnect, compare the code, and approve. The
   client must report an explicit password error.
7. Enter the correct password and reconnect. DeskFlow must prompt again because
   decline, timeout, and wrong-password attempts cannot save trust. Approve and
   confirm that all three lanes connect.
8. Disconnect and reconnect with the correct password. The saved identity must
   reconnect without another pairing modal.
9. Close the server. Move its identity aside without deleting it:

   ```powershell
   $identity = Join-Path $env:LOCALAPPDATA "DeskFlow\identity"
   $backup = Join-Path $env:LOCALAPPDATA "DeskFlow\identity.validation-backup"
   if (Test-Path $backup) { throw "Validation backup already exists; inspect it before continuing." }
   Move-Item -LiteralPath $identity -Destination $backup
   ```

10. Restart the server so it creates a new identity. The client must reject the
    changed identity and require explicit re-pairing. It must not overwrite the
    old pin silently.
11. Click **Forget saved identity and re-pair**, reconnect, compare the new code,
    approve, and confirm success.

Keep `identity.validation-backup` until the entire matrix is complete.

## Test 4: recover from a corrupt identity safely

Close the normal DeskFlow application. This test redirects `LOCALAPPDATA` so it
cannot damage the real identity.

```powershell
$realLocalAppData = $env:LOCALAPPDATA
$testLocalAppData = Join-Path $env:TEMP "DeskFlow-Identity-Recovery-Validation"
$env:LOCALAPPDATA = $testLocalAppData
run.bat
```

Close DeskFlow after it creates the temporary identity. Then run:

```powershell
$identity = Join-Path $testLocalAppData "DeskFlow\identity"
$pointer = Get-Content (Join-Path $identity "current.json") | ConvertFrom-Json
$key = Join-Path (Join-Path (Join-Path $identity "generations") $pointer.generation) "key.pem"
Set-Content -LiteralPath $key -Value "corrupt validation key"
run.bat
```

Pass if DeskFlow opens, reports that it replaced a damaged identity and that
existing clients must re-pair, and places the damaged generation in the
identity quarantine directory.

Restore the environment before continuing:

```powershell
$env:LOCALAPPDATA = $realLocalAppData
```

## Test 5: validate ports, deadlines, and safe errors

1. Start the server. On the server, run:

   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 5000,5001,5002 |
       Select-Object LocalAddress, LocalPort, State, OwningProcess
   ```

   All three ports must belong to DeskFlow's Python process.
2. Connect with the wrong password. The message must say the password is
   incorrect and tell the user to check the server password.
3. Connect correctly without clearing trust or relaunching. It must succeed.
4. Stop the server and connect. The client must say it cannot reach the server
   and suggest checking the address, port, and server state.
5. Try an unreachable LAN address. The attempt must end automatically within
   the configured timeout.
6. Confirm no error exposes a traceback, private path, password, token,
   clipboard content, private filename, raw TLS exception, `Control Socket
   Error`, or `Data Socket Error`.

Copy each complete red status message into the results file.

## Test 6: validate the compact window and saved role

1. Confirm each app opens at a compact size with no large empty region.
2. Drag every edge/corner and double-click the title bar. The window must not
   resize or maximize.
3. Trigger wrong-password and unreachable-server errors. Each message must wrap
   inside the window, remain readable, and be selectable and copyable. DeskFlow
   must not open a separate error popup.
4. Start the server successfully, close it, and reopen it. The Server tab must
   be selected.
5. Connect the client successfully, close it, and reopen it. The Client tab
   must be selected.
6. Cause a failed connection, close the app, and reopen it. The last successful
   role must remain selected.

## Test 7: validate all layouts and repeated reconnects

Test right, left, top, and bottom positions:

1. Select the client position before starting the server.
2. Connect without relaunching either app.
3. Cross from server to client. The cursor must appear at the adjoining client
   edge with only a tiny safety inset and must not bounce back immediately.
4. Cross back. The server cursor must appear at the corresponding edge.
5. Disconnect and reconnect without closing either app. The attempt must
   connect or show an actionable timed error; it must never hang silently.

After all four positions, disconnect and reconnect three more times on the
final position.

## Test 8: validate keyboard, mouse, Delete, and emergency release

While the server controls the client:

1. In Notepad, test lowercase, uppercase, numbers, punctuation, Backspace,
   Enter, arrows, Tab, Ctrl shortcuts, Alt, and Shift combinations.
2. Test click, double-click, right-click, drag, and scroll.
3. Select a disposable client file and press Delete on the server keyboard.
   Confirm the file leaves the desktop or enters Recycle Bin.
4. Hold modifiers and press `Ctrl+Alt+Shift+Escape` on the server. DeskFlow must
   release forwarded modifiers, disconnect remote control, and restore usable
   local input immediately. It does not need to close both application windows.
5. Reconnect without relaunching and repeat a short typing and mouse check.

## Test 9: validate ordinary clipboard formats and latest-wins behavior

Test both directions:

1. Copy and paste plain text.
2. Copy and paste Unicode text, including emoji and non-Latin characters.
3. Copy and paste a screenshot.
4. Copy formatted HTML/RTF text between applications that preserve formatting.
5. Copy several text and screenshot values quickly. The latest value must win,
   and input must remain responsive.
6. Try a very large disposable clipboard image. DeskFlow may reject it because
   of the size bound, but the secure connection must remain alive and a later
   small text copy must work.

## Test 10: validate repeated small file pastes after Delete

Use disposable `delete-me.txt`, `first-copy.txt`, and `second-copy.txt` files.

1. While remotely controlling the client, delete `delete-me.txt` with the
   server keyboard.
2. Copy `first-copy.txt` from client to server. Wait for completion and both
   toasts to close.
3. Wait ten seconds. Copy `second-copy.txt` from client to server without
   reconnecting. It must complete and must not remain at `Waiting for Windows
   Explorer`.
4. Repeat the two sequential transfers from server to client.
5. Reproduce the earlier sequence: complete one transfer, wait, remotely delete
   another selected file, and complete another transfer.
6. Complete at least five alternating small transfers without reconnecting.
   No transfer may require a DeskFlow relaunch.

## Test 11: measure 100 MiB transfer and inspect encrypted staging

### Create and hash the source file

Create a random file on the sending PC:

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

Immediately before paste:

```powershell
$timer = [Diagnostics.Stopwatch]::StartNew()
```

Immediately after DeskFlow reports completion:

```powershell
$timer.Stop()
$seconds = $timer.Elapsed.TotalSeconds
[pscustomobject]@{
    Seconds = $seconds
    MiBPerSecond = 100 / $seconds
}
```

On the destination:

```powershell
Get-Item "$env:USERPROFILE\Desktop\DeskFlow-100MiB.bin" |
    Select-Object FullName, Length
Get-FileHash "$env:USERPROFILE\Desktop\DeskFlow-100MiB.bin" -Algorithm SHA256
```

Run once server-to-client and once client-to-server. Pass if source and
destination lengths and hashes match and neither direction reproduces the old
250-300 KB/s regression. Record seconds and MiB/s for both directions.

### Compare against `main`

The accepted design requires a same-machine baseline comparison. On each PC,
create the baseline worktree once from the security-revamp repository:

```powershell
$securityRepo = (Resolve-Path .).Path
$baselineRepo = Join-Path (Split-Path $securityRepo -Parent) "DeskFlow-main-baseline"
if (-not (Test-Path $baselineRepo)) {
    git worktree add $baselineRepo main
}
Set-Location $baselineRepo
& (Join-Path $securityRepo "venv\Scripts\python.exe") run.py
```

With both baseline apps running, measure the same 100 MiB file once in each
direction. Record the baseline SHA, seconds, MiB/s, and hashes. Close both
baseline apps, return to `$securityRepo`, start `fix/security-revamp`, and repeat
the measurements. Record the percentage difference. The encrypted revamp must
show no meaningful throughput regression relative to `main`.

### Inspect staging encryption and cleanup

Create a disposable marker file on the sender:

```powershell
$marker = "DESKFLOW-PLAINTEXT-VALIDATION-MARKER`r`n"
$markerPath = Join-Path $env:USERPROFILE "Desktop\DeskFlow-Marker.txt"
[IO.File]::WriteAllText($markerPath, $marker * 100000)
Get-Item $markerPath | Select-Object FullName, Length
```

Create a duplicate destination file:

```powershell
Set-Content "$env:USERPROFILE\Desktop\DeskFlow-Marker.txt" "existing destination placeholder"
```

Paste the marker file and leave Explorer's duplicate-name prompt open. While it
is open, run on the receiver:

```powershell
$staging = Join-Path $env:LOCALAPPDATA "DeskFlow\transfers"
Get-ChildItem $staging -Recurse -File | Select-Object FullName, Length
rg -a -l --fixed-strings "DESKFLOW-PLAINTEXT-VALIDATION-MARKER" $staging
```

Ciphertext may exist, but `rg` must not find the plaintext marker. Complete or
cancel the prompt, wait for the toast to close, wait two seconds, and list the
staging directory again. Files for the completed or cancelled job must be gone.

## Test 12: validate input and clipboard latency during transfer

During each direction of Test 11:

1. Move the mouse continuously between visible targets.
2. Type a sentence in Notepad.
3. Click and scroll.
4. Select a disposable remote file and press Delete.
5. Copy and paste plain text.
6. Copy and paste a screenshot.

Control and clipboard must remain usable without visible multi-second stalls.

During one large transfer, run this in a second client PowerShell window:

```powershell
ping <SERVER_IP> -n 100 |
    Tee-Object "$env:USERPROFILE\Desktop\DeskFlow-ping-during-transfer.txt"
```

Compare loss/minimum/maximum/average with Test 1. Record noticeable pauses and
whether they correlate with transfer-only latency spikes.

## Test 13: validate cancellation and immediate recovery

Run all four cases:

- server-to-client, cancel at source;
- server-to-client, cancel at destination;
- client-to-server, cancel at source;
- client-to-server, cancel at destination.

For each case:

1. Start a 100 MiB transfer and cancel after progress begins.
2. Both windows and both toasts must enter cancellation and clear. No offset
   mismatch, hash error, cancellation echo, stale acknowledgement, or traceback
   may appear.
3. No partial destination file or staging ciphertext may remain.
4. Without reconnecting, transfer a small text file in the same direction. It
   must complete immediately.

## Test 14: validate network-loss and fresh-session recovery

1. Connect and transfer a small file.
2. Disable Wi-Fi on the client. Both apps must leave connected state within the
   timeout, clear active toasts, and restore local control.
3. Re-enable Wi-Fi and reconnect without relaunching DeskFlow.
4. Transfer a small file, plain text, and a screenshot.
5. Repeat while a 100 MiB transfer is active. After reconnecting, the old job
   must not contaminate a new small transfer.

## Test 15: perform a final clean restart

1. Close both apps normally. Confirm ports 5000-5002 are no longer listening on
   the server:

   ```powershell
   Get-NetTCPConnection -LocalPort 5000,5001,5002 -ErrorAction SilentlyContinue
   ```

2. Reopen both apps and verify the saved roles.
3. Connect using the saved pin without a pairing popup.
4. Cross the screen edge, copy text, and transfer one small file.
5. Close both apps. Confirm there are no extra error windows, duplicate pairing
   codes, stuck toasts, locked modifiers, or unexplained Python processes using
   DeskFlow's ports.

## Completion record

Append a dated section to [VALIDATION-RESULTS.md](VALIDATION-RESULTS.md) with:

- tester and date;
- exact SHA tested on both PCs;
- PASS or FAIL for Tests 0-15;
- both Windows and network environments;
- server-to-client and client-to-server 100 MiB elapsed time and MiB/s for
  `main` and `fix/security-revamp`;
- the calculated throughput difference;
- source and destination lengths and SHA-256 hashes;
- idle and during-transfer ping results;
- exact status text and logs for every failure;
- whether any unexpected reconnect or relaunch was required;
- confirmation that staging contained no plaintext marker and was cleaned;
- confirmation that both apps released ports after closing.

Every required test must pass on one identical final SHA before the
security-revamp goal can be marked complete.
