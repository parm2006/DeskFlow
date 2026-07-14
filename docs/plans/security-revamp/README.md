# Security revamp

Rebuild DeskFlow's identity, pairing, session binding, encrypted staging, cancellation, and security UI from `main` at `8b329d8`, following the accepted [design](../../superpowers/specs/2026-07-13-security-revamp-design.md). Prototype security/background branches are abandoned and must not supply implementation code.

## Execution order and status

| Plan | Title | Effort | Depends on | Status |
|---|---|---:|---|---|
| [001](001-secure-identity-and-pairing.md) | Secure identity and pairing | L | — | COMPLETE |
| [002](002-bind-network-session.md) | Bind and deadline all network lanes | L | 001 | COMPLETE |
| [003](003-encrypt-staging-and-cancellation.md) | Encrypt staging and rebuild cancellation | L | 001, 002 | COMPLETE |
| [004](004-security-ui-and-system-verification.md) | Finish security UI and system verification | L | 001–003 | AUTOMATED COMPLETE; TWO-PC PENDING |

The authoritative remaining acceptance work and evidence record is
[VALIDATION.md](VALIDATION.md).

## Dependency notes

- Identity produces the certificate and trust records consumed by session binding.
- Session binding provides the authenticated ownership boundary for transfer cancellation.
- The final plan integrates typed failures and runs the complete acceptance matrix.

## Considered and rejected

- Prototype-branch salvage: rejected because it preserves pin-before-auth, blocking handshakes, quadratic staging reads, and cancellation echoing.
- Single multiplexed connection: rejected because large file work would share scheduling and failure pressure with latency-sensitive input.
- Per-chunk DPAPI: rejected because it is slow and does not provide efficient range access.

## Deferred

- Background daemon, hide/show, synchronized application exit, packaging changes, code signing, Internet relay, and cross-platform support.
