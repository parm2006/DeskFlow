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
* **Security & Encryption**: Python's native `ssl` library for TLS and the `cryptography` package for auto-generating RSA certificates.
* **Clipboard**: `pyperclip` or native OS APIs.
* **GUI / Settings Wrapper**: `customtkinter` (modern, dark-themed UI for starting server/client and entering IP addresses).

---

## Project Structure (Proposed)

```
DeskFlow/
├── LICENSE              # License Information
├── cert.pem             # Auto-generated Public Certificate
├── key.pem              # Auto-generated Private Key
├── known_hosts.json     # Saved IP/Port configurations
├── features.md          # Comprehensive list of DeskFlow features
├── plan.md              # Project roadmap and architecture
├── requirements.txt     # Python dependency file
├── run.bat              # Windows startup script
├── run.py               # Main entry point (starts GUI)
├── app/
│   ├── __init__.py
│   ├── crypto.py        # Auto-generation of TLS Certificates
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
- [x] Establish basic TCP connection between Server and Client.
- [x] Implement edge detection on Server and lock/release cursor.
- [x] Stream mouse coordinates to Client and move Client cursor.

### Phase 1.5 — Network Security & Authentication
- [x] Wrap raw TCP sockets in Python `ssl` module for TLS End-to-End Encryption.
- [x] Implement a basic Authentication handshake (e.g. password required to connect) to prevent unauthorized devices from hijacking the mouse.

### Phase 2 — Keyboard Redirection
- [x] Capture keyboard inputs on Server when Client is active.
- [x] Stream and inject keystrokes onto Client.
- [x] Handle system/modifier keys (Ctrl, Alt, Shift, Win/Cmd).

### Phase 2.5 — Keyboard Security
- [x] Ensure keyboard hooking is strictly limited to when the mouse is physically on the Client screen.
- [x] Implement OS-level suppressions securely so local host keystrokes are never accidentally broadcasted or leaked.

### Phase 3 — Plaintext Clipboard Sync
- [x] Watch clipboard contents for changes using `pyperclip`.
- [x] Send plaintext clipboard payload across the socket on copy events.

### Phase 3.5 — Clipboard Security
- [x] Implement strict payload validation (length checks and type checks) to prevent memory exhaustion or remote code execution.
- [x] Ensure sensitive copied data (passwords) are cleared securely from the clipboard if the connection drops.

### Phase 4 — File Sharing & Drag-and-Drop (ON HOLD)
- [ ] Implement background file transfer server.
- [ ] *Concerns to address before implementation:*
  - **Network Blocking**: Sending large files over the main socket will freeze mouse/keyboard inputs. Requires a dedicated secondary TCP socket.
  - **Path Traversal Attacks**: Incoming filenames must be rigorously sanitized and locked to a strict `DeskFlow_Downloads` directory to prevent system overwrites.
  - **Malware Execution**: Files should only be saved to disk. Automatic execution upon transfer is a critical RCE vulnerability.
  - **OS Drag Limitations**: Grabbing files mid-drag on Windows bypasses `pynput` and requires complex Windows Shell (Explorer) hooks, which may conflict with edge detection.

### Phase 5 - Multi-Monitor Scaling and Resolution Sync
- [x] Handle physical monitor size disparities (e.g. 32-inch vs 13-inch).
- [x] Currently uses relative y_ratio, but physical movement distances can feel disconnected.
- [x] Implement absolute or configured pixel mapping instead of strict relative ratios to fix offset entry points on different sized screens.

### Backlog / Known Bugs
- [x] App Close while Client active: If the DeskFlow GUI is closed via the 'X' button while control is switched to the client, the network connection isn't cleanly closed and the invisible `ctk_toplevel` overlay may linger or stop the mouse from working properly. Needs proper teardown/disconnect hooks on window destroy.
- [x] Network Error Handling: If the Client attempts to connect with the correct IP but wrong port (or encounters other socket connection edge cases), the GUI crashes instead of showing a graceful error message. Need to implement robust exception handling for the connection process.
- [ ] Rich Clipboard Support: Currently, clipboard synchronization only supports plaintext strings. Investigate OS-native APIs to support copying and pasting formatted text (RTF) and raw image data across the network.

### Quality of Life Improvements
- [x] Known Hosts Autofill: Create a local `known_hosts.json` file (ignored by Git) to save successful IP/Port combinations. The Client GUI should automatically fill in the last used IP and Port, or provide a dropdown of previously successful connections.
- [x] Disconnect Buttons & Dynamic UI Status: Add red Stop/Disconnect buttons to the GUI that dynamically appear upon connection and gracefully reset the UI across both computers when the socket is closed or drops.

### Phase 6 — Spatial Layout Configuration
- [x] Introduce visual 3x3 layout selector in the GUI to place Client (Top, Bottom, Left, Right).
- [x] Update edge detection logic to dynamically respect the selected layout boundary.
- [x] Perform network handshake to configure the Client's return-edge automatically based on its relative position.