# Plan 001: Secure identity and pairing

> Execute test-first. Stop at any unplanned trust-state or Windows key-storage fork.

## Status

- **Effort**: L
- **Risk**: HIGH
- **Depends on**: none
- **Planned at**: `8b329d8`, 2026-07-13
- **Completed at**: `f995183`, 2026-07-13

## Current state and intent

`app/crypto.py` stores an unencrypted cwd-relative key. `app/network.py` accepts any server certificate. Introduce a `%LOCALAPPDATA%` identity store, encrypted PEM plus DPAPI-protected password, atomic validation/migration/recovery, canonical peer pins, short pairing codes, delayed trust commit, and typed pairing outcomes.

## Steps and gates

1. Add failing identity-store tests for generation, encrypted-at-rest key, match validation, legacy migration, corrupt quarantine, and atomic recovery. Implement only enough identity storage to pass.
2. Add failing trust-store tests for canonical keys, path containment, atomic pin writes, lookup, and re-pair deletion. Implement the store.
3. Add failing pairing-state tests proving decline and failed authentication never persist trust, while successful authenticated binding commits once. Implement the state owner and pairing-code helper.
4. Run `\.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*identity*.py" -v` and the full suite.

## Done criteria

- Private key bytes are not plaintext on disk; TLS loads the encrypted PEM directly.
- Legacy cwd identity migration is safe and one-time.
- No failed or declined attempt changes trust.
- Full tests and compile check pass.
