# DeskFlow — Cross-PC Mouse, Keyboard, and Clipboard Sharing

DeskFlow is a lightweight, wireless KVM utility written in Python. It allows two separate computers (on the same local network) to share a single mouse, keyboard, clipboard, and drag-and-drop file stream.

---

## High-Level Architecture

```
[Server/Host PC] (Physical Mouse/KB attached)
        ↓
    OS Hooks (pynput) → Captures movement / keystrokes
        ↓
    Network Socket (TCP) → Sends coordinates / payloads over Wi-Fi
        ↓
[Client PC] (Secondary Screen)
        ↓
    Network Handler → Receives coordinates / payloads
        ↓
    OS Input Synthesizer (pynput) → Injects inputs into OS
```

---

## Core Features & Scope

### 1. Mouse Roaming
* **Edge Detection**: Server detects when mouse reaches the screen border (e.g., right edge of Server screen).
* **Cursor Lock**: Once transitioned, the Server cursor is locked to the edge of the Server screen.
* **Movement Delta Sending**: Server continuously sends relative mouse coordinates (DX, DY) to the Client.
* **Cursor Transition Back**: If the Client cursor reaches its left edge, control switches back to the Server.

### 2. Keyboard Redirection
* **Active Hooking**: When screen focus is shifted to the Client, the Server intercepts all keystrokes.
* **Packet Sending**: Keystrokes are serialized and sent over TCP.
* **Injection**: Client simulates the keypresses/releases on the secondary machine.

### 3. Shared Clipboard
* **Clipboard Watcher**: Background thread on both machines monitors clipboard changes.
* **Sync Payload**: When a new string is copied, it is sent over the connection.
* **Write Clipboard**: The receiving machine writes the string to its local clipboard.

### 4. File Drag & Drop (Wireless File Transfer)
* **File Drag Detection**: Detects when a file drag crosses the active boundary.
* **TCP File Stream**: Transfers the file in chunks over a dedicated port.
* **Target Drop**: Simulates file drop events on the client system.

---

## Technology Stack

* **Language**: Python 3.10+
* **Input Hooking & Injection**: `pynput` (cross-platform support for Windows, macOS, and Linux).
* **Network Protocol**: TCP sockets (`socket` and `selectors`/`asyncio` for non-blocking networking).
* **Clipboard**: `pyperclip` or native OS APIs.
* **GUI / Settings Wrapper**: `customtkinter` (modern, dark-themed UI for starting server/client and entering IP addresses).

---

## Project Structure (Proposed)

```
DeskFlow/
├── config.json          # Screen layouts, IP addresses, port settings
├── requirements.txt     # Python dependency file
├── run.py               # Main entry point (starts GUI)
├── app/
│   ├── __init__.py
│   ├── gui.py           # CustomTkinter interface
│   ├── server.py        # Host server logic (inputs capture & send)
│   ├── client.py        # Client receiver logic (inputs injector)
│   ├── network.py       # Socket connection manager
│   ├── clipboard.py     # Clipboard sync helper
│   └── input_handler.py # OS-level input hook/injection wrapper
```

---

## Implementation Roadmap

### Phase 1 — Basic Socket Connectivity & Mouse Roaming
* Establish basic TCP connection between Server and Client.
* Implement edge detection on Server and lock/release cursor.
* Stream mouse coordinates to Client and move Client cursor.

### Phase 2 — Keyboard Redirection
* Capture keyboard inputs on Server when Client is active.
* Stream and inject keystrokes onto Client.
* Handle system/modifier keys (Ctrl, Alt, Shift, Win/Cmd).

### Phase 3 — Clipboard Sync
* Watch clipboard contents for changes.
* Send clipboard text payload across the socket on copy events.

### Phase 4 — File Sharing & Drag-and-Drop
* Implement background file transfer server.
* Capture file references on drag start and transmit files to client's temporary cache directory.
