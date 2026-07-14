# Plan 002: Bind and deadline all network lanes

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: 001
- **Planned at**: `8b329d8`, 2026-07-13

## Current state and intent

Control and data servers authenticate independently with booleans, handshakes can block the only accept loop, and receive-loop cleanup can affect replacement sockets. Make control own a session, issue expiring one-use data/file tokens, bind every lane to the session and certificate, and enforce per-phase deadlines with generation-safe cleanup.

## Steps and gates

1. Add failing tests for TLS/auth deadlines, accepted-socket isolation, stale receive loops, and single callback delivery; implement generation-owned connections.
2. Add failing session-token tests for expiry, replay, wrong purpose, wrong session, and cross-client lane mixing; implement a bounded token registry.
3. Wire client control-first connection, approval, authentication, token-bound data/file lanes, and delayed pin commit. Keep file and control framing bounded.
4. Run focused network/file-transport tests, then the full suite and compile check.

## Done criteria

- A stalled or failed peer cannot block later connections.
- Two clients cannot contribute different lanes to one connection.
- Token replay and cross-purpose use fail.
- All sockets and worker lifetimes have one cleanup owner.

