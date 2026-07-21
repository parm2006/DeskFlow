# DeskFlow two-PC manual validation

This suite validates the currently checked-out DeskFlow revision. Both PCs must
run the same full commit. Run the FIFO queue test last; a FIFO-specific failure
does not invalidate an earlier core result.

Use two Windows PCs on the same private network. Call them `SERVER_PC` and
`CLIENT_PC` in your notes. Use disposable files only.

Do not publish IP addresses, usernames, computer names, Wi-Fi names, MAC
addresses, fingerprints, or absolute paths. Replace them with placeholders
such as `<SERVER_IP>` and `<USER_PATH>` before sharing output.

If DeskFlow traps input, press `Ctrl+Alt+Shift+Escape` on the server keyboard.

## Test order and stopping rule

Run the sections in order.

1. Sections 0-10 are the core non-file release gate. Stop at the first failure.
2. Sections 11-15 characterize the current single-file implementation. A
   failure here is a file-specific result; it does not erase the core result.
3. Section 16 is the FIFO queue gate. Run it only after Sections 0-15 have been
   recorded and only when FIFO is claimed to be implemented.

For each section, record `PASS`, `FAIL`, or `NOT RUN`. Preserve the exact status
text and the nearby console lines for failures.

## 0. Revision and automated gate

Run on both PCs:

```powershell
git pull --ff-only
git branch --show-current
git rev-parse HEAD
git rev-parse --short HEAD
git status --short
.\venv\Scripts\python.exe -m compileall -q app tests run.py
.\venv\Scripts\python.exe -m unittest discover -s tests -q
git diff --check
```

Pass when:

- both PCs print the same full commit and intended branch;
- both `git status --short` outputs are empty;
- compilation succeeds;
- both full test suites finish with `OK`;
- `git diff --check` prints nothing.

The automated suite covers internal behavior that is impractical to attack by
hand: message bounds, job-ID validation, expired requests, manifest limits,
token replay and expiry, certificate binding across lanes, encrypted staging
records, path traversal, hash verification, cancellation races, and malformed
network frames. Do not replace this gate with manual testing.

## 1. Environment record and network baseline

Record only private notes. Do not paste raw output into a public issue.

On each PC:

```powershell
Get-CimInstance Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber

Get-NetAdapter |
    Where-Object Status -eq "Up" |
    Select-Object Name, MediaType, LinkSpeed
```

On `CLIENT_PC`, test the server connection:

```powershell
ping <SERVER_IP> -n 20
```

Record the Windows build, Wi-Fi or Ethernet, link rate, packet loss, and
minimum/average/maximum latency. Proceed when the client can reach the server.
If packet loss is nonzero, repeat the ping and mark the environment unstable;
do not mislabel existing network loss as a DeskFlow failure. Keep the latency
result for comparison during a large transfer.

## 2. Launch, window, and saved settings

1. Run `run.bat` on both PCs.
2. Confirm the main window is compact and all controls fit.
3. Drag the edges and double-click the title bar. The window must not resize or
   maximize.
4. On `SERVER_PC`, select **Left**, start successfully, close DeskFlow, and
   reopen it. Confirm the Server role and Left direction return.
5. Repeat with **Right**, **Top**, and **Bottom**. Confirm the most recently
   selected direction returns each time.
6. On `CLIENT_PC`, connect successfully, close DeskFlow, and reopen it. Confirm
   the Client role returns.
7. Cause one failed client connection, close the app, and reopen it. A failed
   attempt must not replace the last successful role.

Pass when the window remains usable and DeskFlow remembers the last successful
role and server direction.

## 3. Local identity and stored trust

After DeskFlow has created its identity, inspect it on each PC. Use the
Microsoft Store Python `LocalCache\Local\DeskFlow` location if Windows has
redirected `%LOCALAPPDATA%\DeskFlow`.

```powershell
$identity = Join-Path $env:LOCALAPPDATA "DeskFlow\identity"
$pointer = Get-Content (Join-Path $identity "current.json") | ConvertFrom-Json
$generation = Join-Path (Join-Path $identity "generations") $pointer.generation
Get-Content (Join-Path $generation "key.pem") -TotalCount 1
Get-ChildItem $generation | Select-Object Name, Length
```

Pass when:

- the key begins with `-----BEGIN ENCRYPTED PRIVATE KEY-----`;
- the generation contains `cert.pem`, `key.pem`, and `key-password.dpapi`;
- the repository contains no temporary plaintext key.

After pairing, inspect the client trust directory:

```powershell
$peers = Join-Path $env:LOCALAPPDATA "DeskFlow\peers"
Get-ChildItem $peers -File | Select-Object Name, Length
```

Pass when peer filenames are hash-like rather than IP-address filenames and no
legacy `<SERVER_IP>.fingerprint` file exists. Keep the actual names private.

### 3.1 Isolated damaged-identity recovery

Run this on one PC with normal DeskFlow closed. It redirects `LOCALAPPDATA` so
the test cannot alter the real identity:

```powershell
$realLocalAppData = $env:LOCALAPPDATA
$testLocalAppData = Join-Path $env:TEMP "DeskFlow-Identity-Recovery-Validation"
$env:LOCALAPPDATA = $testLocalAppData
run.bat
```

Close the temporary DeskFlow window after it creates an identity. Corrupt only
the temporary key, then restart:

```powershell
$identity = Join-Path $testLocalAppData "DeskFlow\identity"
$pointer = Get-Content (Join-Path $identity "current.json") | ConvertFrom-Json
$key = Join-Path (Join-Path (Join-Path $identity "generations") $pointer.generation) "key.pem"
Set-Content -LiteralPath $key -Value "corrupt validation key"
run.bat
```

Pass when DeskFlow opens, explains that it replaced a damaged identity, and
quarantines the damaged generation. Restore the real environment before any
other test:

```powershell
$env:LOCALAPPDATA = $realLocalAppData
```

## 4. Pairing, passwords, and trust lifecycle

1. Start the server with a disposable test password.
2. On the client, click **Forget saved identity and re-pair**, then connect.
3. Confirm only the client displays the approval modal. The server displays its
   comparison code without an approval popup.
4. Confirm both short codes match. The code text must be white, the title bar
   must be dark, the full fingerprint must be selectable, and both buttons must
   fit.
5. Decline. Confirm the client says `Pairing was declined.` and does not save
   trust.
6. Retry and leave the modal untouched. Confirm it closes on timeout and a new
   attempt prompts again.
7. Connect with the wrong password, approve the matching code, and confirm the
   password error is specific and actionable.
8. Connect with the correct password. Confirm another approval is required,
   approve it, and complete the connection.
9. Disconnect and reconnect. Confirm the saved identity connects without
   another modal.
10. On the server, move the real identity directory to a private backup, start
    DeskFlow so it creates a new identity, and reconnect. Confirm the client
    rejects the changed identity until you explicitly forget and re-pair.

Pass when decline, timeout, and wrong-password attempts save no trust; saved
trust reconnects; and an identity change never overwrites trust silently. Keep
the identity backup until all testing finishes.

## 5. Connection lifecycle and safe errors

With the server running, confirm all three lanes listen under one process:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5000,5001,5002 |
    Select-Object LocalAddress, LocalPort, State, OwningProcess
```

Then test:

1. wrong password;
2. correct password immediately afterward;
3. server stopped;
4. an unused private-network address;
5. disconnect and reconnect three times without relaunching;
6. disable the client network adapter, wait for disconnection, enable it, and
   reconnect without relaunching.

Pass when each attempt succeeds or ends within its deadline with an actionable
message. No message may reveal a password, token, fingerprint, clipboard value,
private filename, absolute path, traceback, raw socket error, or TLS detail.

## 6. Screen geometry and control return

Test Left, Right, Top, and Bottom separately:

1. Select the direction and start the server.
2. Connect the client.
3. Cross from server to client at several points along the shared edge.
4. Confirm the cursor enters at the corresponding client edge with a tiny
   safety inset and does not bounce back immediately.
5. Cross back and confirm the server cursor returns at the matching edge.
6. Disconnect, reconnect, and repeat one crossing without restarting either
   app.

Pass when all four layouts work and neither cursor becomes trapped.

## 7. Mouse, keyboard, NumPad, and Delete

Open Notepad and File Explorer on the controlled client.

1. Type lowercase, uppercase, numbers, punctuation, emoji input, Backspace,
   Enter, Tab, arrows, Home, End, Page Up, and Page Down.
2. Test Ctrl, Shift, and Alt shortcuts.
3. Click, double-click, right-click, drag, select text, and scroll.
4. Select a disposable client file and press Delete from the server keyboard.
5. With NumLock on, type `0123456789`, decimal, `/`, `*`, `-`, and `+` from the
   keypad.
6. With NumLock off, confirm the keypad performs navigation.
7. Turn NumLock on again and confirm keypad digits return.

Pass when every input arrives once, with the intended meaning, and local input
resumes after crossing back.

## 8. Modifier release and emergency recovery

Run this section carefully in Notepad so accidental shortcuts cause no damage.

1. Hold left Ctrl while crossing to the client. Release Ctrl, type `d`, then
   type ordinary text. `d` must type normally; it must not trigger a shortcut.
2. Repeat with right Ctrl, left/right Shift, left/right Alt, and the Windows key.
3. Hold a modifier while crossing back to the server, release it, and type.
4. While controlling the client, press `Ctrl+Alt+Shift+Escape` on the server.
   DeskFlow must disconnect and restore usable local input immediately.
5. Reconnect and perform a short keyboard and mouse check.
6. Close the client normally while a modifier is active, then release the
   physical key. Confirm the client PC does not retain a logical modifier.
7. Restart the client, focus its PowerShell console locally, press Ctrl+C to
   stop DeskFlow, and release Ctrl. Open another application locally and type.
   The client PC must not retain Ctrl after console termination.

Pass when no modifier remains logically pressed after a crossing, disconnect,
emergency release, or normal shutdown.

## 9. Ordinary clipboard formats and latest-wins behavior

Run every required and secondary item server-to-client and client-to-server.
Use the same DeskFlow revision on both PCs.

### Required: Google Docs to Google Docs

1. Copy and paste plain ASCII text.
2. Copy and paste Unicode text containing emoji and non-Latin characters.
3. Copy formatted text containing a heading, text color, a link, and a list.
4. Select one inline image in a Google Doc, copy it, and paste it into another
   Google Doc.
5. In one selection, copy formatted text plus one or more inline images and
   paste it into another Google Doc. Confirm both formatting and images survive.
6. Copy and paste a small table containing text and an image.
7. Copy the same Google Docs selection twice and paste after each copy.

### Secondary: Word to Word

8. Copy and paste formatted text.
9. Select, copy, and paste one image.
10. In one selection, copy and paste formatted text plus an inline image.

Google Docs to Word and Word to Google Docs are observation-only checks. Do not
fail DeskFlow when the same cross-application paste also fails locally on one
PC.

### Regressions

11. Copy and paste a screenshot into an image-capable application.
12. Copy text A, text B, and screenshot C quickly. Confirm C is the available
    clipboard value.
13. Repeat rapid text and screenshot copying ten times while crossing screens.
14. Copy a large disposable image. If DeskFlow rejects it because of a size
    bound, confirm the connection remains alive and a later small text copy
    works.
15. Copy a disposable file and confirm ordinary clipboard sync does not log or
    serialize its path; complete the file checks in Section 10 separately.
16. Disconnect and reconnect, then copy and paste a small formatted selection.

Pass when every required Google Docs case succeeds in both directions, the
newest ordinary clipboard action wins, rejected content does not break the
session, and file clipboard authority remains separate. Record Word results as
secondary evidence.

If a required same-application case fails, record only the portable format
kind, source order, and byte count observed at capture and publication. Never
record clipboard contents, encoded data, image metadata, file paths, or private
registered format names. Stop before adding arbitrary formats, resource
downloading, or OLE behavior.

## 10. Clipboard authority around an unpasted file

Run each sequence in both directions.

1. Copy disposable file A but do not paste it. Copy text B and paste. B must
   paste; file A must not start.
2. Copy file A but do not paste it. Copy screenshot C and paste it into an
   image-capable app. C must paste; file A must not start.
3. Copy text A, then file B, then press Ctrl+V in Explorer. File B must be the
   offered item.
4. Copy file A, then file B, then press Ctrl+V once. Only the newest file offer
   may be used.
5. Advertise a file, disconnect before pasting, reconnect, copy text, and paste.
   The previous session's file must not intercept the new text.

Pass when the newest clipboard action controls Ctrl+V and an unpasted file
never blocks later text or images.

## 11. Console diagnostics and privacy

Keep both `run.bat` consoles visible while repeating one connection, boundary
crossing, text copy, screenshot copy, and disposable small-file paste.

Pass when logs describe state changes with sentence-style capitalization but
never reveal clipboard contents, passwords, tokens, fingerprints, IP addresses,
private filenames, absolute paths, raw file bytes, TLS details, or tracebacks.

This section finishes the core non-file release gate.

## 12. Single small-file baseline

Use a new empty destination folder on each PC.

1. Copy one small disposable file on the server. Confirm no transfer starts
   until you press Ctrl+V in client Explorer.
2. Paste once. Confirm the destination name, size, and SHA-256 match.
3. Wait for both toasts to close, then paste a different small file in the same
   direction without reconnecting.
4. Repeat both transfers client-to-server.
5. Copy one folder containing nested disposable files and paste it once. Compare
   the resulting tree and hashes.

Pass when each requested item appears once, matches its source, and sequential
single jobs work without reconnecting.

## 13. Clipboard restoration, duplicate names, and failure filename

1. Put recognizable disposable text or an image on the destination clipboard.
2. Paste a file whose name already exists. Choose **Don't copy** in Explorer.
3. Paste into the original text/image application. The clipboard value from
   step 1 must still work.
4. Copy a disposable source file, then rename or remove it before requesting the
   paste. Trigger the safe transfer failure.
5. Repeat with a long disposable filename.

Pass when cancellation clears promptly, the virtual file no longer owns the
clipboard, and the failure toast uses a white title containing a sanitized,
ellipsized failed filename. The filename must not be duplicated in the detail
text. Record any expected console probe noise separately from actual failure.

## 14. Large file, throughput, and input priority

Create a random 100 MiB file on the sending PC:

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
Get-Item $path | Select-Object Length
Get-FileHash $path -Algorithm SHA256
```

Run three transfers in each direction. For every run, record elapsed seconds,
MiB/s, source hash, and destination hash. Do not publish the full paths.

During one transfer:

1. move the mouse continuously;
2. type in an application other than the active Explorer copy window;
3. click and scroll;
4. cross screens and return;
5. copy and paste text;
6. copy and paste a screenshot;
7. run a 100-packet ping and compare it with Section 1.

Pass when all six destination hashes match, no transfer reproduces the historic
250-300 KB/s regression, and control/ordinary clipboard traffic remains usable
without multi-second stalls. Record all six speeds; do not judge performance
from one unusually fast run.

The Explorer window performing a synchronous virtual-file paste may delay its
own clicks until the copy finishes. That specific window is not a failure for
this baseline. Other applications and DeskFlow control must remain responsive.

## 15. Cancellation, disconnect, encrypted staging, and recovery

Run four cancellation cases with the 100 MiB file:

- server-to-client, cancelled at the source;
- server-to-client, cancelled at the destination;
- client-to-server, cancelled at the source;
- client-to-server, cancelled at the destination.

For each case, confirm both toasts clear, no partial destination remains, and a
new small-file paste works without reconnecting.

Then disconnect once while waiting for Explorer and once during active transfer.
After each disconnect, reconnect and paste text, a screenshot, and a small file.
No stale job or toast may enter the new session.

To inspect staging encryption, create a large disposable file containing the
marker `DESKFLOW-PLAINTEXT-VALIDATION-MARKER`. During transfer, run on the
destination:

```powershell
$staging = Join-Path $env:LOCALAPPDATA "DeskFlow\transfers"
rg -a -l --fixed-strings "DESKFLOW-PLAINTEXT-VALIDATION-MARKER" $staging
```

Pass when `rg` finds no plaintext marker and completed, failed, and cancelled
jobs leave no DeskFlow staging data after their cleanup period.

## 16. FIFO file-paste queue — run last

This remains the final file-queue gate. Record the observed behavior without
weakening the earlier core result. When FIFO is claimed by the revision under
test, every item below is mandatory.

Create files A, B, C, and D with distinct random contents and record each hash.
Make A large enough to remain active while you request the others.

### 16.1 Ordered success

1. Paste A.
2. While A is active, copy and paste B.
3. While A is still active, copy and paste C.
4. Let every job finish.

Pass when A, B, and C start and complete strictly in paste-request order. B and
C must not transmit or publish while A is active. All hashes must match.

### 16.2 Immutable queued contents

1. While A is active, request B.
2. After requesting B, overwrite or rename B's original source.
3. Copy unrelated text and an image.
4. Let the queue continue.

Pass when queued B uses the immutable snapshot captured for its request, while
the newer text and image remain usable as ordinary clipboard values.

### 16.3 Failure advances once

1. Start A.
2. Queue a disposable B that will fail safely.
3. Queue C after B.

Pass when A completes, B fails once with its filename, and C starts exactly
once afterward. The queue must neither stall nor skip C.

### 16.4 Cancellation advances once

1. Start A and queue B and C.
2. Cancel A at the source; repeat the test by cancelling at the destination.
3. In a separate run, allow A to finish and cancel queued/active B.

Pass when each cancellation terminalizes on both PCs exactly once and the next
queued job begins exactly once without reconnecting.

### 16.5 Clipboard remains usable during the queue

While A, B, and C are pending or active, paste plain text and a screenshot in
both directions and continue moving and typing across screens.

Pass when ordinary clipboard and input remain responsive and no ordinary copy
is converted into, blocked by, or lost behind a file job.

### FIFO acceptance

FIFO passes only if Sections 16.1-16.5 pass in both transfer directions. Record
the observed start and terminal order, for example:

```text
A started -> A completed -> B started -> B failed -> C started -> C completed
```

## Final clean restart

After all applicable tests:

1. Close both apps normally.
2. Confirm ports 5000-5002 no longer listen on the server.
3. Confirm no unexpected DeskFlow Python process remains.
4. Reopen both apps and confirm saved roles and direction.
5. Reconnect with saved trust, cross once, type, paste text and a screenshot,
   and perform one single small-file paste.
6. Close both apps again.

Pass when the clean restart requires no repair, re-pair, or stale-process kill.

## Results template

```text
Full commit on SERVER_PC: <FULL_COMMIT>
Full commit on CLIENT_PC: <SAME_FULL_COMMIT>

0  Revision and automated gate: PASS/FAIL/NOT RUN
1  Environment and network baseline: PASS/FAIL/NOT RUN
2  Launch, window, and saved settings: PASS/FAIL/NOT RUN
3  Local identity and stored trust: PASS/FAIL/NOT RUN
4  Pairing, passwords, and trust: PASS/FAIL/NOT RUN
5  Connection lifecycle and safe errors: PASS/FAIL/NOT RUN
6  Screen geometry and control return: PASS/FAIL/NOT RUN
7  Mouse, keyboard, NumPad, and Delete: PASS/FAIL/NOT RUN
8  Modifier release and emergency recovery: PASS/FAIL/NOT RUN
9  Ordinary clipboard and latest-wins: PASS/FAIL/NOT RUN
10 Clipboard authority around files: PASS/FAIL/NOT RUN
11 Console diagnostics and privacy: PASS/FAIL/NOT RUN
12 Single small-file baseline: PASS/FAIL/NOT RUN
13 Clipboard restoration and failure filename: PASS/FAIL/NOT RUN
14 Large-file throughput and input priority: PASS/FAIL/NOT RUN
15 Cancellation, disconnect, staging, recovery: PASS/FAIL/NOT RUN
16 FIFO queue: PASS/FAIL/NOT IMPLEMENTED/NOT RUN
Final clean restart: PASS/FAIL/NOT RUN

First failure:
Expected:
Observed:
Exact status text:
Relevant redacted console lines:
Reconnect or relaunch required: YES/NO
```
