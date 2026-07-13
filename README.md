# <img src="assets/DeskFlow.ico" width="32" height="32" alt="DeskFlow icon" /> DeskFlow

DeskFlow is a lightweight, wireless KVM utility written in Python. It allows sharing a single mouse, keyboard, and rich clipboard (including text and images) between two computers on the same local network.

## Features
* **Wireless Mouse Roaming**: Border edge detection switches control seamlessly.
* **Keyboard Redirection**: Captures and routes input (including modifier keys) with local suppression.
* **Rich Clipboard Sync**: Synchronizes text and images with fast zlib compression and loop/freeze protection.
* **TLS Encryption**: Secure communication via SSL/TLS socket wrappers.

## Emergency Exit
If the mouse/keyboard focus becomes stuck on the client, press **`Ctrl + Alt + Shift + Escape`** on the server keyboard to immediately break the connection and restore local control.

## Getting Started

### Prerequisites
* Windows 10/11 on both PCs
* Python 3.10+

### Setup & Run
1. Clone the repository on both computers.
2. Run `run.bat` on each PC (it sets up the virtual environment, installs dependencies, and boots the GUI).
3. On the **Server (Host)**: Enter a password, select the Client position, and click **Start Server**.
4. On the **Client**: Enter the Server's IP address, Port, password, and click **Connect**.

### Background mode

DeskFlow can keep sharing input and clipboard data without opening its configuration window. Use the packaged executable or the Python launcher with the same role settings:

```powershell
DeskFlow.exe --daemon --role server --password "your-password" --port 5000
DeskFlow.exe --daemon --role client --host 192.168.1.20 --password "your-password" --port 5000
```

The process stays active in the signed-in Windows user session and can be stopped with `Ctrl+C` when launched from a terminal. For repeat use, place the chosen command in a Windows shortcut or scheduled task configured to run at user logon. The daemon does not require the GUI window to remain open.

The application icon is stored in [`assets/DeskFlow.ico`](assets/DeskFlow.ico) and is used for both the Tk window and packaged executable.
