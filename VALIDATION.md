# DeskFlow two-PC file-paste validation

Use the same build on both PCs. Run each direction: desktop as server, then
laptop as server. Do not merge this branch until every required check passes.

## 0. Start and verify the connection

On the server PC, start DeskFlow and select **Server (Host)**. Then run:

```powershell
Get-NetTCPConnection -State Listen |
    Where-Object LocalPort -in 28903,28904,28905 |
    Format-Table LocalAddress,LocalPort,State,OwningProcess
```

On the client PC, replace the address below with the server's IPv4 address:

```powershell
$serverIp = '192.168.86.87'
28903,28904,28905 | ForEach-Object {
    Test-NetConnection $serverIp -Port $_ |
        Select-Object RemoteAddress,RemotePort,TcpTestSucceeded
}
```

All three ports must succeed. Connect DeskFlow and confirm that the mouse,
keyboard, text clipboard, and rich clipboard work in both directions.

## 1. Native same-PC paste

Perform these checks on both PCs:

1. Copy a local file and paste it on the same PC. Windows must perform a native
   paste. DeskFlow must not show a transfer toast.
2. Copy the same file again and paste it on the same PC. Windows may add
   `- Copy` to the name. DeskFlow must remain idle.
3. Copy a file on the other PC, then copy a new local file. Paste locally. The
   new local file must win; DeskFlow must not paste the older remote file.

## 2. Cross-PC route latch

1. Copy one file on the source PC.
2. Move to the other screen and press Ctrl+V.
3. Immediately move the pointer back to the source screen.

The paste must finish on the screen that was active when Ctrl+V was pressed.
Later pointer movement must not redirect or stall the transfer.

Repeat in both directions.

## 3. Large files and folders

Create a test folder larger than 500 MB with several files and nested folders.
Paste it in both directions. Confirm:

- the manifest preparation does not fail after one second;
- the UI and control connection remain responsive while DeskFlow hashes files;
- the transfer completes without a short-read or apparent file-size ceiling;
- every received file has the expected size and content;
- a second copy made after completion becomes the authoritative clipboard item.

If practical, repeat with a sparse or disposable file larger than 4 GiB to
exercise Windows' 64-bit virtual-file descriptors.

## 4. Windows collision dialog

Paste into a directory that already contains the same name.

1. Choose **Copy and Replace** (or the Windows equivalent). The transfer must
   complete once, and the toast must close.
2. Repeat and choose **Don't copy** or **Cancel**. The transfer must become
   cancelled or failed and the toast must close within 20 seconds.
3. Repeat, press the DeskFlow toast's **Cancel** button while the Windows dialog
   is open, then try to continue the Windows dialog. No file data may transfer,
   and later reads must fail as cancelled.

Windows Explorer may leave an empty folder that it created before cancellation.
DeskFlow cannot safely delete that folder because Explorer does not provide an
authoritative destination path or ownership token. DeskFlow must never guess a
path and delete a user-created folder.

## 5. Cancellation and recovery

Cancel each of these transfers from the DeskFlow toast in both directions:

- before Explorer opens a stream;
- during network transfer;
- while the collision dialog is open;
- after disabling Wi-Fi.

The toast must close, both peers must reach a terminal state, and the next text,
file, and folder paste must work without restarting DeskFlow.

After cancellation, check the encrypted staging area on each PC:

```powershell
$roots = @(
    (Join-Path $env:LOCALAPPDATA 'DeskFlow\transfers'),
    (Join-Path $env:LOCALAPPDATA 'Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\Local\DeskFlow\transfers')
)
$roots | Where-Object { Test-Path $_ } | ForEach-Object {
    Get-ChildItem $_ -Recurse -File | Select-Object FullName,Length
}
```

No cancelled job should retain staging files after its streams close.

## 6. Record the result

Record the build or commit, server IP, client IP, direction, selection size,
result, elapsed time, and any console error. A passing automated suite does not
replace this two-PC test.
