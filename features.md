# DeskFlow Features

## Currently Implemented

### Wireless Mouse Roaming
* **Edge Detection Transition**: Moving the mouse to the right edge of the Server screen instantly captures the cursor and transitions it to the Client screen, completely wirelessly.
* **Instant Return**: Moving the mouse back to the left edge of the Client screen instantly returns control to the Server.
* **Scroll & Click Forwarding**: All mouse scroll events and Left/Right/Middle clicks are faithfully reproduced on the Client machine.
* **Low Latency**: TCP Nagle's algorithm is disabled to ensure instantaneous transmission of pixel-perfect coordinates.

### Display Scaling & Sync
* **Multi-Monitor DPI Awareness**: The Server inherently scales coordinates to match the logical dimensions of the Client, meaning physical transitions between a large desktop monitor and a small laptop screen feel perfectly mapped.

### End-to-End Security
* **Auto-Generated TLS Certificates**: DeskFlow dynamically generates local self-signed RSA certificates to lock down the connection without requiring complex configuration.
* **SSL Socket Encryption**: All mouse movements and data are scrambled over a secure TLS layer, preventing anyone on the local Wi-Fi from reading coordinates.
* **Password Authentication**: A handshake blocks rogue computers from hooking into the Host. If the passwords do not exactly match, the Server forcefully aborts the connection.

### Quality of Life UI
* **CustomTkinter Overlay**: DeskFlow uses a highly invisible GUI overlay to seamlessly trap the mouse during client control, preventing underlying OS applications from interfering.
* **Known Hosts Autofill**: The Client intelligently remembers past successful connections in a local Git-ignored `known_hosts.json` file. The GUI dropdown automatically populates and auto-selects your most recent server IP and Port.

---

## Planned Features

### Keyboard Redirection (Coming Soon)
* Global keyboard hooking.
* Broadcasting and simulating all keystrokes (including modifier combinations) on the Client.
* Strict host-side suppression to ensure keystrokes aren't accidentally typed on the Server while the Client is active.

### Clipboard Synchronization (Coming Soon)
* Background listeners that watch the OS clipboard.
* Payload transmission and validation to securely push text to the opposite machine.

### File Drag & Drop (Coming Soon)
* Dedicated background stream to transfer files dropped near the screen edge.
* Automatic caching and execution/dropping on the target machine.
