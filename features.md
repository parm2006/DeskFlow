# DeskFlow Features

## Currently Implemented

### Wireless Mouse Roaming
* **Edge Detection Transition**: Moving the mouse to the right edge of the Server screen instantly captures the cursor and transitions it to the Client screen, completely wirelessly.
* **Scroll & Click Forwarding**: All mouse scroll events and Left/Right/Middle clicks are faithfully reproduced on the Client machine.

### Keyboard Redirection (v2.0s)
* **Global Keyboard Hooking**: Captures all keyboard input on the Server when the Client is active.
* **Low-Latency Streaming**: Broadcasts and simulates all keystrokes (including modifier combinations like Ctrl, Alt, Shift, Win/Cmd) on the Client.
* **Strict OS-Level Suppression**: Ensures keystrokes are completely suppressed on the Server side while the Client is active, guaranteeing you don't accidentally type passwords on the host screen.

### End-to-End Security
* **Auto-Generated TLS Certificates**: DeskFlow dynamically generates local self-signed RSA certificates to lock down the connection without requiring complex configuration.
* **SSL Socket Encryption**: All mouse movements, keystrokes, and data are scrambled over a secure TLS layer, preventing anyone on the local Wi-Fi from reading inputs.
* **Password Authentication**: A handshake blocks rogue computers from hooking into the Host. If the passwords do not exactly match, the Server forcefully aborts the connection.

### Quality of Life UI
* **CustomTkinter Overlay**: DeskFlow uses a highly invisible GUI overlay to seamlessly trap the mouse during client control, preventing underlying OS applications from interfering.
* **Known Hosts Autofill**: The Client intelligently remembers past successful connections in a local Git-ignored `known_hosts.json` file. The GUI dropdown automatically populates and auto-selects your most recent server IP and Port.
* **Dynamic Connection Controls**: The interface provides dedicated red `Disconnect` and `Stop Server` buttons that only appear during active connections.
* **Reactive Status Engine**: If a network connection is forcefully dropped (e.g., losing Wi-Fi), the GUI on both computers instantly reacts, updating statuses, releasing the physical mouse, and resetting buttons without ever freezing.
* **Input Validation**: The UI actively prevents starting servers or connecting clients if required fields (like passwords) are left blank.

---

## Planned Features

### Clipboard Synchronization (Coming Soon)
* Background listeners that watch the OS clipboard.
* Payload transmission and validation to securely push text to the opposite machine.

### File Drag & Drop (Coming Soon)
* Dedicated background stream to transfer files dropped near the screen edge.
* Automatic caching and execution/dropping on the target machine.
