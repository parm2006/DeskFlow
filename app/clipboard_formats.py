import base64
import binascii
import hashlib
import json
import zlib
from dataclasses import dataclass


MIB = 1024 * 1024
FORMAT_LIMITS = {
    "unicode_text": 5 * MIB,
    "html": 5 * MIB,
    "rtf": 5 * MIB,
    "chromium_web_custom": 5 * MIB,
    "png": 32 * MIB,
    "dib": 32 * MIB,
    "dibv5": 32 * MIB,
}
MAX_SNAPSHOT_BYTES = 40 * MIB
MAX_ENCODED_MESSAGE_BYTES = 60 * MIB


class ClipboardPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class ClipboardEntry:
    kind: str
    data: bytes

    def __post_init__(self):
        if self.kind not in FORMAT_LIMITS:
            raise ClipboardPayloadError("clipboard format kind is unsupported")
        if not isinstance(self.data, bytes):
            raise ClipboardPayloadError(
                f"clipboard format {self.kind} data must be bytes"
            )
        if len(self.data) > FORMAT_LIMITS[self.kind]:
            raise ClipboardPayloadError(
                f"clipboard format {self.kind} exceeds its size limit"
            )


@dataclass(frozen=True)
class ClipboardSnapshot:
    entries: tuple[ClipboardEntry, ...]

    def __post_init__(self):
        entries = tuple(self.entries)
        object.__setattr__(self, "entries", entries)
        if not entries:
            raise ClipboardPayloadError("clipboard snapshot must not be empty")
        if len(entries) > len(FORMAT_LIMITS):
            raise ClipboardPayloadError("clipboard snapshot has too many formats")
        if any(not isinstance(entry, ClipboardEntry) for entry in entries):
            raise ClipboardPayloadError("clipboard snapshot entries are invalid")
        kinds = [entry.kind for entry in entries]
        if len(kinds) != len(set(kinds)):
            raise ClipboardPayloadError("clipboard snapshot has duplicate formats")
        if sum(len(entry.data) for entry in entries) > MAX_SNAPSHOT_BYTES:
            raise ClipboardPayloadError("clipboard snapshot exceeds its size limit")

    def fingerprint(self):
        hasher = hashlib.sha256()
        for entry in sorted(self.entries, key=lambda e: e.kind):
            hasher.update(entry.kind.encode("utf-8"))
            hasher.update(entry.data)
        return hasher.hexdigest()


def _encoded_message_size(message):
    try:
        return len(json.dumps(message, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as error:
        raise ClipboardPayloadError("clipboard message is not valid JSON") from error


def _validate_offer_identity(revision, session_id):
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision <= 0
    ):
        raise ClipboardPayloadError("clipboard offer revision is invalid")
    if (
        not isinstance(session_id, str)
        or not session_id
        or len(session_id) > 128
    ):
        raise ClipboardPayloadError("clipboard offer session is invalid")
    return revision, session_id


def encode_clipboard_message(
    snapshot, offer_revision=None, session_id=None
):
    if not isinstance(snapshot, ClipboardSnapshot):
        raise ClipboardPayloadError("clipboard value must be a snapshot")
    snapshot = ClipboardSnapshot(snapshot.entries)
    revisioned = offer_revision is not None or session_id is not None
    if revisioned:
        _validate_offer_identity(offer_revision, session_id)
    message = {
        "type": "clipboard_sync",
        "version": 3 if revisioned else 2,
        "formats": [
            {
                "kind": entry.kind,
                "raw_size": len(entry.data),
                "data": base64.b64encode(zlib.compress(entry.data, level=6)).decode(
                    "ascii"
                ),
            }
            for entry in snapshot.entries
        ],
    }
    if revisioned:
        message["offer_revision"] = offer_revision
        message["session_id"] = session_id
    if _encoded_message_size(message) > MAX_ENCODED_MESSAGE_BYTES:
        raise ClipboardPayloadError("clipboard message exceeds its encoded size limit")
    return message


def clipboard_message_identity(message):
    if not isinstance(message, dict):
        raise ClipboardPayloadError("clipboard message must be an object")
    version = message.get("version")
    if version == 2:
        return None, None
    if version != 3:
        raise ClipboardPayloadError("clipboard message version is unsupported")
    return _validate_offer_identity(
        message.get("offer_revision"), message.get("session_id")
    )


def _decode_entry_data(kind, value, limit):
    if not isinstance(value, str):
        raise ClipboardPayloadError(f"clipboard format {kind} data must be text")
    try:
        compressed = base64.b64decode(value, validate=True)
        decoder = zlib.decompressobj()
        data = decoder.decompress(compressed, limit + 1)
    except (binascii.Error, ValueError, zlib.error) as error:
        raise ClipboardPayloadError(
            f"clipboard format {kind} data is invalid"
        ) from error
    if (
        len(data) > limit
        or not decoder.eof
        or decoder.unconsumed_tail
        or decoder.unused_data
    ):
        raise ClipboardPayloadError(f"clipboard format {kind} data is invalid")
    return data


def decode_clipboard_message(message):
    if not isinstance(message, dict):
        raise ClipboardPayloadError("clipboard message must be an object")
    if _encoded_message_size(message) > MAX_ENCODED_MESSAGE_BYTES:
        raise ClipboardPayloadError("clipboard message exceeds its encoded size limit")
    if message.get("type") != "clipboard_sync":
        raise ClipboardPayloadError("clipboard message type is invalid")
    version = message.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version not in (2, 3):
        raise ClipboardPayloadError("clipboard message version is unsupported")
    expected_fields = {"type", "version", "formats"}
    if version == 3:
        expected_fields.update(("offer_revision", "session_id"))
        clipboard_message_identity(message)
    if set(message) != expected_fields:
        raise ClipboardPayloadError("clipboard message fields are invalid")
    formats = message["formats"]
    if not isinstance(formats, list):
        raise ClipboardPayloadError("clipboard formats must be a list")
    if not formats:
        raise ClipboardPayloadError("clipboard formats must not be empty")
    if len(formats) > len(FORMAT_LIMITS):
        raise ClipboardPayloadError("clipboard message has too many formats")

    entries = []
    kinds = set()
    declared_total = 0
    for value in formats:
        if not isinstance(value, dict) or set(value) != {
            "kind",
            "raw_size",
            "data",
        }:
            raise ClipboardPayloadError("clipboard format fields are invalid")
        kind = value["kind"]
        if not isinstance(kind, str) or kind not in FORMAT_LIMITS:
            raise ClipboardPayloadError("clipboard format kind is unsupported")
        if kind in kinds:
            raise ClipboardPayloadError("clipboard message has duplicate formats")
        kinds.add(kind)

        raw_size = value["raw_size"]
        if (
            isinstance(raw_size, bool)
            or not isinstance(raw_size, int)
            or raw_size < 0
            or raw_size > FORMAT_LIMITS[kind]
        ):
            raise ClipboardPayloadError(
                f"clipboard format {kind} size is invalid"
            )
        declared_total += raw_size
        if declared_total > MAX_SNAPSHOT_BYTES:
            raise ClipboardPayloadError("clipboard snapshot exceeds its size limit")

        remaining = MAX_SNAPSHOT_BYTES - sum(len(entry.data) for entry in entries)
        data = _decode_entry_data(
            kind,
            value["data"],
            min(FORMAT_LIMITS[kind], remaining),
        )
        if len(data) != raw_size:
            raise ClipboardPayloadError(
                f"clipboard format {kind} size does not match its data"
            )
        entries.append(ClipboardEntry(kind, data))

    return ClipboardSnapshot(entries)
