# Portable ordered clipboard sync design

**Status:** Approved for implementation planning

**Planned from:** revision `15a8092efe7ea21cc865f643be046ce546207bad`

**Primary acceptance target:** Google Docs to Google Docs

**Secondary acceptance target:** Microsoft Word to Microsoft Word

## Goal

DeskFlow must reproduce the useful, portable part of the source Windows
clipboard on the other PC. In particular, copying a Google Docs selection that
contains formatted text and inline images should paste into Google Docs with the
same structure and images. Image-only, rich-text-only, and plain-text copies
must continue to work.

DeskFlow is not trying to translate between application document models.
Google Docs to Word is not an acceptance requirement because that paste is not
reliable even on one PC. Both DeskFlow peers are expected to run the new
clipboard protocol version.

## Why the current implementation breaks mixed copies

Windows does not store one universal clipboard value. A copy operation exposes
an ordered set of alternate representations, and the destination application
chooses the first representation it understands.

The current implementation loses information at three points:

1. `ClipboardHandler._read_clipboard()` reads only Unicode text, DIB, HTML, and
   RTF. It does not capture registered PNG or DIBV5.
2. `_poll_clipboard()` forwards only when the text or DIB hash changes. An
   HTML-only, RTF-only, PNG-only, or DIBV5-only copy can therefore disappear.
3. `inject()` always republishes text, DIB, HTML, then RTF. This replaces the
   source application's format preference order with DeskFlow's fixed order.

A mixed Google Docs copy can rely on HTML plus an image representation and on
the source format order. Capturing individual formats but publishing them in a
different order is not equivalent to cloning the portable clipboard offer.

## Chosen approach

Capture and republish an explicit allowlist of portable Windows clipboard
formats as an ordered snapshot:

- `CF_UNICODETEXT`
- registered `HTML Format`
- registered `Rich Text Format`
- registered `PNG`
- registered `Chromium Web Custom MIME Data Format`
- `CF_DIB`
- `CF_DIBV5`

The sender enumerates formats with `EnumClipboardFormats`, keeps allowlisted
entries in that exact order, and transfers each entry as bounded bytes. The
receiver validates the complete snapshot before opening the clipboard, then
publishes the same entries in the same order.

Unicode text is canonicalized as UTF-16LE with one terminating NUL. HTML, RTF,
Chromium web custom data, PNG, DIB, and DIBV5 remain opaque bytes; DeskFlow
does not parse, sanitize, rewrite, fetch, or transcode their contents. The
Chromium format is one fixed, bounded browser format rather than a generic
registered-format mechanism.

## Clipboard v2 message

Ordinary clipboard sync keeps the existing `clipboard_sync` message type but
uses a versioned ordered body:

```text
{
  "type": "clipboard_sync",
  "version": 2,
  "formats": [
    {
      "kind": "html",
      "raw_size": 1234,
      "data": "<zlib-compressed bytes encoded as Base64>"
    },
    ...
  ]
}
```

`kind` is one of `unicode_text`, `html`, `rtf`, `chromium_web_custom`, `png`,
`dib`, or `dibv5`.
Each kind may appear at most once. Unknown, duplicate, malformed, oversized,
or trailing-data entries reject the entire message before clipboard mutation.
DeskFlow does not partially publish a rejected snapshot.

Version 1 and version 2 peers are not content-compatible. A mismatched peer
must reject or ignore the unsupported clipboard body safely without breaking
input or the network connection. Capability negotiation and downgrade logic are
not part of this effort because the two PCs are updated together.

## Bounds

Apply limits before copying or inflating data wherever Windows and zlib expose
the size:

| Format | Maximum raw bytes |
|---|---:|
| Unicode text | 5 MiB |
| HTML | 5 MiB |
| RTF | 5 MiB |
| Chromium web custom data | 5 MiB |
| PNG | 32 MiB |
| DIB | 32 MiB |
| DIBV5 | 32 MiB |
| Complete snapshot | 40 MiB |
| Encoded clipboard message | 60 MiB |

The 60 MiB message ceiling remains below `app.network.MAX_MESSAGE_SIZE` (64
MiB). If any per-format, aggregate, or encoded limit is exceeded, reject the
whole copy and log only the format kind and reason. Do not log clipboard bytes,
text, image metadata, file paths, or encoded payloads.

Rejecting a whole oversized mixed snapshot is intentional. Silently dropping
one representation could produce a clipboard that pastes but has missing
images or incorrect formatting.

## Change detection and loop prevention

The Windows clipboard sequence number is the authority for a local copy. Every
new local sequence that has a non-file allowlisted snapshot is eligible for
forwarding, even when its bytes equal the previous copy. This fixes HTML-only
and image-format-only copies and preserves the user's ability to copy identical
content twice.

DeskFlow records the sequence created by its own remote injection and suppresses
that sequence only. Content hashes are removed from loop prevention. If the user
copies locally while injection is settling, the newer sequence remains pending
and is processed after injection ends.

`LatestWinsSender` remains the outbound scheduler: one send may be active and
one replaceable pending snapshot may exist. Sequence-driven capture does not
create an unbounded queue.

## File clipboard boundary

`CF_HDROP`, shell formats, virtual-file OLE data, and file paths remain in the
existing file-paste subsystem. When a new clipboard sequence contains
`CF_HDROP`, DeskFlow updates file availability and does not serialize any of its
ordinary fallback formats as a rich snapshot.

The ordinary clipboard v2 allowlist must never grow to include file or shell
formats. This prevents path disclosure and preserves the current file-offer
authority model.

## Error behavior

- Validate and decode a remote snapshot completely before `EmptyClipboard`.
- A malformed or oversized remote payload leaves the existing local clipboard
  unchanged and does not disconnect the peer.
- A local capture rejected by a bound is not sent. A later valid copy must work.
- Clipboard lock failures retain the current bounded retry behavior.
- Logs identify state and format kind only; they never contain content.

## Acceptance matrix

Run each accepted case server-to-client and client-to-server.

### Google Docs to Google Docs (required)

- plain and Unicode text
- multiple paragraphs whose line breaks survive, with headings, color, links,
  and lists
- one selected inline image
- formatted text plus one or more inline images in one selection, including
  the image's Docs layout mode when the source offers it
- a small table containing text and an image
- the same selection copied twice

### Word to Word (secondary)

- formatted text
- one selected image
- formatted text plus an inline image

### Regressions

- screenshot to image-capable application
- rapid text/image copies remain latest-wins
- malformed and oversized payloads do not break the session
- a file copy remains owned by the file-transfer subsystem
- disconnect/reconnect followed by a valid copy still works

Google Docs to Word, Word to Google Docs, and other cross-application fidelity
are observations only, not pass/fail gates.

## Out of scope

- arbitrary registered clipboard formats other than the one fixed, bounded
  Chromium web custom format above
- Office-private formats, OLE objects, and remote `IDataObject` proxying
- `CF_HDROP`, shell ID lists, file descriptors, file contents, or drop effects
- SVG, metafiles, and bitmap transcoding
- downloading or rewriting external resources referenced by HTML
- application-specific conversion between Google Docs and Word
- changing the file-transfer protocol

If Google Docs mixed content still fails after the ordered allowlist is proven
to be captured and republished byte-for-byte, stop. Record privacy-safe format
names, order, and byte counts, then return for a new design decision. Do not add
arbitrary formats, resource downloading, or OLE proxying inside this effort.
