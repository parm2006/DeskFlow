# DeskFlow security revamp

## Goal

Rebuild DeskFlow security and transfer reliability from `main` without merging, cherry-picking, or copying implementation code from `fix/security-upgrade` or `fix/background-daemon`. Background and daemon behavior is out of scope until this design passes its automated and two-computer acceptance gates.

## Security boundary

DeskFlow protects network traffic, clipboard payloads in transit, private identity material, peer trust records, and every DeskFlow-owned partial or completed transfer artifact. The final file Explorer writes into the user's chosen destination remains an ordinary usable file. Endpoint compromise, Internet relay, source deletion, remote execution, and code signing are outside this change.

## Identity and pairing

- Store identity and trust under `%LOCALAPPDATA%\DeskFlow`, never the working directory.
- Store the private key as password-encrypted PEM. Protect the random PEM password with Windows DPAPI so Python's TLS context can load the encrypted key directly without a plaintext temporary file.
- Write key, password, and certificate transactionally; validate that the key matches the certificate before use. Migrate a valid legacy plaintext identity once. Quarantine corrupt identity files and expose a deliberate regeneration outcome that tells the user existing peers must re-pair.
- Represent connection progress explicitly: `TLS_CANDIDATE -> AWAITING_APPROVAL -> AUTHENTICATING -> BINDING_LANES -> CONNECTED`, with typed terminal failures.
- On first pairing, show the same short code on server and client and show the full fingerprint on the client. Save the pin only after password authentication and secondary-lane binding succeed. Decline, timeout, wrong password, disconnect, or lane failure saves no trust.
- Keep an always-available inline Re-pair action. Store pins by a canonical hashed peer identifier rather than raw host text.

## Session-bound transport

Retain separate control, clipboard/data, and file lanes to protect input latency. The authenticated control lane owns one logical session and issues one-use random tokens for the data and file lanes. A secondary lane must present its token and match the control lane's server certificate; replay, expiry, cross-session use, and a lane from another client are rejected.

Apply bounded TCP-connect, TLS-handshake, approval, password-authentication, and lane-binding deadlines. Each receive loop owns only its socket generation, so an old loop cannot disconnect a replacement connection. Server handshakes cannot block the accept loop. Frames remain bounded and authenticated; logs and GUI errors never include passwords, tokens, clipboard contents, file contents, or private paths.

## Encrypted staging

Use a random in-memory AES-256-GCM key per transfer job. Store independently authenticated fixed-size records with unique nonces and AAD binding the job, path, record index, plaintext offset, and length. Maintain the record index in memory; interrupted jobs are not resumed. Startup deletes abandoned ciphertext.

Explorer range reads decrypt only intersecting records and never hold the receiver condition lock during disk IO or decryption. Verification hashes the original plaintext incrementally. A verified DeskFlow cache remains encrypted; Explorer receives plaintext only through the virtual stream. Cleanup owns partial, completed-cache, cancellation, disconnect, and startup-recovery paths.

## Cancellation

One idempotent cancellation operation carries a job ID and cancellation ID. The initiator enters `CANCELLING`, the peer applies the transition once and returns an acknowledgement without echoing another request, and both enter `CANCELLED`. A bounded tombstone retains terminal job identity so late chunks, completion frames, duplicate requests, and stale acknowledgements are ignored. Cancellation during verification cannot be mistaken for verification success. The next queued job starts without reconnecting.

## UI and errors

Replace fixed one-line status rendering with a resizable inline status panel whose details wrap to available width and can be selected and copied. First-pair approval is an intentional interaction; connection failures and re-pair recovery remain in the main window without extra error popups. Error contracts preserve the failed action, safe reason, consequence, and next action.

## Verification

Automated tests cover identity migration and corruption, no plaintext key residue, delayed pin commit, pairing decline, mismatch and re-pair, every deadline, stale receive loops, secondary-lane token replay/cross-session mixing, encrypted record random reads and tamper detection, cleanup, cancellation from both peers, duplicate and late frames, cancellation during verification, and an immediate following transfer.

Measure encrypted staging and end-to-end 100 MB transfer against `main` on the same machines. Reject any meaningful throughput or control-latency regression; range-read cost must scale with requested records rather than file prefix size. The two-computer matrix runs both directions and covers reconnect, first pair, saved pair, changed identity, re-pair, text/screenshot/input responsiveness, cancel from either side, and a successful next transfer.

