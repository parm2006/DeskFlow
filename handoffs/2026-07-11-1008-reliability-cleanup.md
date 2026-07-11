# reliability-cleanup | thread: deskflow-hardening | status: active | Plan DeskFlow reliability work, beginning with clipboard synchronization, before cleanup and feature expansion.

## What changed
- No DeskFlow source files were changed in this conversation.
- Repository architecture was reviewed across `app/network.py`, `app/clipboard_handler.py`, `app/client.py`, `app/server.py`, `app/input_handler.py`, and `app/gui.py`.
- A global `handoff` skill was created at `C:\Users\parth\.agents\skills\handoff` for future Codex app and CLI sessions.
- The agreed milestone order is: reliability first, repository quality second, product features third.

## What works (verified)
- Repository state is clean on branch `main` at commit `aa66cd9` — `git -c safe.directory='C:/Users/parth/Projects/DeskFlow' status --short` produced no entries.
- Recent repository history is readable — `git -c safe.directory='C:/Users/parth/Projects/DeskFlow' log -5 --oneline` showed `aa66cd9 Implement automatic resolution-based mouse scaling` as HEAD.
- DeskFlow already separates GUI, client/server orchestration, networking, input handling, cryptography, and clipboard handling into dedicated modules — verified by source inspection.
- Current clipboard implementation supports text, DIB images, HTML, and RTF using polling, zlib compression, Base64 encoding, and content hashes — verified in `app/clipboard_handler.py`.

## Broken or open
- **Clipboard synchronization is reported as shaky** — likely risk areas identified during inspection include 500 ms polling, hash-only echo suppression, shared mutable payload dictionaries, injection timing races, clipboard-lock retries, and large Base64 JSON messages without message IDs, ordering, acknowledgements, or explicit size limits at the network framing layer. Next: reproduce specific failure modes and design a reliable text-and-image protocol before editing code.
- **Clipboard is wiped on every disconnect/stop** — `ClipboardHandler.stop()` calls `wipe_clipboard()`, which may unexpectedly destroy the user's local clipboard. Next: decide whether secure wiping is truly desired; default recommendation is to preserve local clipboard contents.
- **TLS does not authenticate the server identity** — the client uses `CERT_NONE`, so traffic is encrypted but susceptible to an active local-network impersonation attack. Next: add certificate fingerprint pairing/trust in a later reliability/security slice.
- **No automated tests are present** — protocol framing, state transitions, clipboard deduplication, and disconnect cleanup currently lack regression coverage. Next: introduce tests during the reliability milestone before structural cleanup.
- **Clipboard scope remains a user decision** — recommendation is to stabilize text and images first, then add HTML/RTF after the core protocol is reliable.

## Key facts
- Branch: main
- Commit: aa66cd9
- Parent handoff: none
- Decisions not yet captured elsewhere: use the milestone order reliability → repository quality → product experience; start clipboard work with text and images unless the user chooses full rich clipboard; do not assume a Codex CLI session can see the Codex app conversation.

## Resume by
1. Read this file and `handoffs/index.md`, then inspect the current clipboard and network implementations before making changes.
2. Ask the user to confirm whether the first clipboard milestone should cover text only, text plus images (recommended), or text/images/HTML/RTF.
3. Reproduce or characterize the observed clipboard failures, then propose 2–3 reliability designs with trade-offs before implementation.

Open question for the user: Should the first reliability slice guarantee text and images only, or preserve HTML and RTF in the initial redesign?
