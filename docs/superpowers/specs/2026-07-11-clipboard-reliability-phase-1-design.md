# Clipboard Reliability Phase 1 Design

## Goal

DeskFlow will synchronize plain text and Windows DIB images reliably between two connected peers. This phase establishes a small, versioned clipboard protocol with deterministic validation, delivery reporting, duplicate suppression, and automated tests. HTML and RTF remain deferred until this protocol works in production.

## Scope

Phase 1 supports one content item per clipboard message:

- UTF-8 text, up to 5 MiB before transport encoding.
- Windows DIB image bytes, up to 50 MiB after decompression.

The phase also protects socket framing from concurrent writers and preserves the local clipboard when DeskFlow disconnects or stops.

Phase 1 excludes HTML, RTF, file transfer, clipboard history, offline delivery, and chunked image transfer. Existing rich-format code may remain temporarily, but the Phase 1 send and receive paths will neither advertise nor guarantee it.

## Current Failure Model

The current implementation has two confirmed structural risks:

1. Multiple application threads may call `NetworkNode.send_message()` concurrently. The method sends each header and body together, but it has no lock. Two `sendall()` calls can overlap on the same stream and corrupt the length-prefixed frame sequence.
2. `ClipboardHandler` stores only the last text hash and image hash. This state cannot distinguish a new message from a retry, a delayed duplicate, or a remote injection that failed. It also updates hashes before confirming clipboard injection.

Other observable weaknesses include unbounded network frame lengths, validation after JSON allocation, MD5 content hashes, fixed retry sleeps, and unconditional clipboard wiping during shutdown.

## Protocol Envelope

Every outbound clipboard item uses this JSON envelope:

```json
{
  "type": "clipboard_sync",
  "version": 1,
  "message_id": "uuid4 string",
  "content_type": "text/plain; charset=utf-8",
  "content_sha256": "lowercase hex digest",
  "uncompressed_size": 12,
  "encoding": "utf-8",
  "payload": "hello world"
}
```

Images use `content_type: image/dib`, `encoding: zlib+base64`, and a SHA-256 digest of the original DIB bytes. A message contains either text or an image, never both.

The receiver returns one terminal response:

```json
{
  "type": "clipboard_ack",
  "version": 1,
  "message_id": "the received uuid",
  "status": "applied"
}
```

Valid statuses are `applied`, `duplicate`, and `rejected`. A rejected acknowledgement includes a stable reason code for logs and tests, such as `unsupported_version`, `invalid_envelope`, `size_limit`, `digest_mismatch`, or `clipboard_unavailable`. Acknowledgements do not trigger automatic retransmission in Phase 1; they make delivery outcomes observable and prepare the protocol for bounded retries later.

## Data Flow

For a local change, the clipboard watcher reads a stable snapshot, selects text or image content, and creates a new immutable envelope. Text takes precedence when both formats exist because Windows commonly exposes text alongside richer clipboard formats. The handler records the outbound message ID only after the data channel accepts the complete frame for sending.

The network layer serializes each frame under one per-connection send lock. It rejects outbound frames above the configured maximum. The receive loop rejects a declared frame length above that maximum before reading or allocating the body.

For a remote change, the receiver validates envelope fields, UUID syntax, content type, encoding, declared size, decoded size, and SHA-256 digest. It checks a bounded cache of recent message IDs before injection. A duplicate receives `duplicate` without touching the clipboard.

After validation, the handler attempts clipboard injection with bounded backoff. It records the injected content digest and message ID only after Windows accepts the data. It then returns `applied`. The next local clipboard notification compares its digest with the bounded injected-digest cache and suppresses the echo once. A failed injection returns `rejected` and leaves deduplication state unchanged.

## State and Concurrency

`NetworkNode` owns a send lock. Connection teardown and send failure remain idempotent so concurrent failures emit one effective disconnect transition.

`ClipboardHandler` owns its mutable state behind a lock:

- running and injecting flags;
- the last observed Windows sequence number;
- a bounded cache of recent remote message IDs;
- a bounded cache of recently injected content digests.

Caches have fixed capacities and discard their oldest entries. They prevent unbounded growth while covering delayed duplicate notifications. Clipboard callbacks receive fresh dictionaries; callers never mutate handler-owned payload state.

## Error Handling

The receiver rejects malformed data without opening the Windows clipboard. Image decompression uses the declared uncompressed size as a hard limit and rejects trailing or oversized output. Network parsing catches invalid UTF-8 and JSON, logs a concise reason, and closes the connection when framing integrity is uncertain.

Clipboard access uses a small bounded backoff schedule instead of one fixed delay. The handler always closes an opened clipboard in `finally`. Failure returns an explicit result to the protocol layer.

Stopping the handler stops and joins its polling thread within a bounded timeout. It never empties the user's clipboard. Secure wiping, if desired later, must become an explicit opt-in policy.

## Compatibility

Both peers must understand protocol version 1 for guaranteed Phase 1 synchronization. A peer rejects an unsupported version rather than guessing at payload semantics. This repository does not need rolling compatibility between different DeskFlow releases during Phase 1.

HTML and RTF will later reuse the same envelope, validation, acknowledgement, and deduplication rules with new content types and format-specific codecs.

## Testing

Automated tests will isolate Windows clipboard access behind a small adapter or injected backend. Tests will cover:

- text and DIB envelope creation and decoding;
- invalid fields, unsupported versions, size limits, decompression bounds, and digest mismatch;
- duplicate message IDs and one-time suppression of injected-content echoes;
- state remaining unchanged after failed injection;
- bounded clipboard-lock retries and clipboard preservation on stop;
- maximum frame enforcement before body allocation;
- concurrent sends producing intact, ordered frames;
- acknowledgement status for applied, duplicate, and rejected messages;
- client and server routing without mutating shared payload dictionaries.

The test suite will run without a live GUI or physical second computer. A final manual check on two Windows machines will copy repeated text, rapid alternating text, small and large screenshots, and identical content copied twice as distinct user actions.

## Success Criteria

Phase 1 is complete when:

1. All automated protocol, handler, and network tests pass.
2. Text and DIB images synchronize in both directions during the manual two-machine check.
3. Rapid copies do not corrupt the connection or bounce indefinitely.
4. Duplicate network delivery does not rewrite or resend clipboard content.
5. Oversized or malformed messages fail safely with a logged reason.
6. Disconnecting DeskFlow preserves each machine's clipboard.

## Implementation Boundaries

The implementation may introduce focused protocol and clipboard-adapter modules when that makes pure logic testable. It will avoid unrelated GUI, input, certificate, packaging, and repository cleanup. TLS identity verification remains a later security slice.
