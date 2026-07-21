import unittest
import base64
import copy
import json
import zlib
from dataclasses import FrozenInstanceError
from unittest.mock import patch

from app import clipboard_formats
from app.clipboard_formats import (
    ClipboardEntry,
    ClipboardPayloadError,
    ClipboardSnapshot,
    decode_clipboard_message,
    encode_clipboard_message,
)


class ClipboardSnapshotTests(unittest.TestCase):
    def test_snapshot_preserves_non_default_format_order(self):
        entries = [
            ClipboardEntry("html", b"html"),
            ClipboardEntry("png", b"png"),
            ClipboardEntry("unicode_text", b"text"),
            ClipboardEntry("dibv5", b"dibv5"),
        ]

        snapshot = ClipboardSnapshot(entries)
        entries.reverse()

        self.assertEqual(
            [entry.kind for entry in snapshot.entries],
            ["html", "png", "unicode_text", "dibv5"],
        )
        self.assertIsInstance(snapshot.entries, tuple)

    def test_entry_and_snapshot_are_immutable(self):
        entry = ClipboardEntry("html", b"html")
        snapshot = ClipboardSnapshot([entry])

        with self.assertRaises(FrozenInstanceError):
            entry.kind = "rtf"
        with self.assertRaises(FrozenInstanceError):
            snapshot.entries = ()

    def test_entry_rejects_unknown_kind_and_non_bytes_data(self):
        with self.assertRaises(ClipboardPayloadError):
            ClipboardEntry("private_format", b"secret")
        with self.assertRaises(ClipboardPayloadError):
            ClipboardEntry("html", "not bytes")

    def test_snapshot_rejects_empty_and_duplicate_formats(self):
        with self.assertRaises(ClipboardPayloadError):
            ClipboardSnapshot([])
        with self.assertRaises(ClipboardPayloadError):
            ClipboardSnapshot(
                [
                    ClipboardEntry("html", b"first"),
                    ClipboardEntry("html", b"second"),
                ]
            )

    def test_entry_rejects_data_above_its_format_limit(self):
        with patch.dict(clipboard_formats.FORMAT_LIMITS, {"html": 3}):
            with self.assertRaises(ClipboardPayloadError):
                ClipboardEntry("html", b"four")

    def test_snapshot_rejects_aggregate_data_above_total_limit(self):
        entries = [
            ClipboardEntry("html", b"abc"),
            ClipboardEntry("rtf", b"def"),
        ]

        with patch.object(clipboard_formats, "MAX_SNAPSHOT_BYTES", 5):
            with self.assertRaises(ClipboardPayloadError):
                ClipboardSnapshot(entries)

    def test_snapshot_rejects_more_than_six_entries_first(self):
        with self.assertRaisesRegex(ClipboardPayloadError, "too many"):
            ClipboardSnapshot([object()] * 7)


class ClipboardCodecTests(unittest.TestCase):
    @staticmethod
    def _message(*entries):
        return encode_clipboard_message(ClipboardSnapshot(entries))

    def test_v2_round_trip_preserves_order_and_does_not_mutate_inputs(self):
        snapshot = ClipboardSnapshot(
            [
                ClipboardEntry("html", b"<b>hello</b>"),
                ClipboardEntry("png", b"png-bytes"),
                ClipboardEntry("unicode_text", "hello\0".encode("utf-16le")),
                ClipboardEntry("dibv5", b"dibv5-bytes"),
            ]
        )
        original_entries = snapshot.entries

        message = encode_clipboard_message(snapshot)
        untouched_message = copy.deepcopy(message)
        decoded = decode_clipboard_message(message)

        self.assertEqual(message["type"], "clipboard_sync")
        self.assertEqual(message["version"], 2)
        self.assertEqual(
            [entry["kind"] for entry in message["formats"]],
            ["html", "png", "unicode_text", "dibv5"],
        )
        self.assertEqual(decoded, snapshot)
        self.assertEqual(snapshot.entries, original_entries)
        self.assertEqual(message, untouched_message)

    def test_decoder_rejects_unsupported_version_and_extra_fields(self):
        message = encode_clipboard_message(
            ClipboardSnapshot([ClipboardEntry("html", b"html")])
        )

        unsupported = copy.deepcopy(message)
        unsupported["version"] = 1
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(unsupported)

        extra = copy.deepcopy(message)
        extra["unexpected"] = True
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(extra)

        extra_entry = copy.deepcopy(message)
        extra_entry["formats"][0]["unexpected"] = True
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(extra_entry)

    def test_codec_requires_snapshot_and_object_message(self):
        with self.assertRaises(ClipboardPayloadError):
            encode_clipboard_message({"html": b"html"})
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message([])

    def test_decoder_rejects_wrong_field_types_and_unknown_formats(self):
        message = self._message(ClipboardEntry("html", b"html"))

        wrong_version_type = copy.deepcopy(message)
        wrong_version_type["version"] = True
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(wrong_version_type)

        wrong_size_type = copy.deepcopy(message)
        wrong_size_type["formats"][0]["raw_size"] = True
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(wrong_size_type)

        unknown = copy.deepcopy(message)
        unknown["formats"][0]["kind"] = "private"
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(unknown)

        not_a_list = copy.deepcopy(message)
        not_a_list["formats"] = {}
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(not_a_list)

    def test_decoder_rejects_duplicate_and_declared_size_mismatch(self):
        duplicate = self._message(
            ClipboardEntry("html", b"html"),
            ClipboardEntry("rtf", b"rtf"),
        )
        duplicate["formats"][1]["kind"] = "html"
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(duplicate)

        mismatch = self._message(ClipboardEntry("html", b"html"))
        mismatch["formats"][0]["raw_size"] += 1
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(mismatch)

    def test_decoder_rejects_invalid_truncated_and_trailing_compression(self):
        invalid = self._message(ClipboardEntry("html", b"html"))
        invalid["formats"][0]["data"] = "not base64!"
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(invalid)

        truncated = self._message(ClipboardEntry("html", b"html"))
        compressed = base64.b64decode(truncated["formats"][0]["data"])
        truncated["formats"][0]["data"] = base64.b64encode(
            compressed[:-1]
        ).decode("ascii")
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(truncated)

        trailing = self._message(ClipboardEntry("html", b"html"))
        compressed = base64.b64decode(trailing["formats"][0]["data"])
        trailing["formats"][0]["data"] = base64.b64encode(
            compressed + b"trailing"
        ).decode("ascii")
        with self.assertRaises(ClipboardPayloadError):
            decode_clipboard_message(trailing)

    def test_codec_enforces_per_format_and_aggregate_raw_limits(self):
        per_format = self._message(ClipboardEntry("html", b"four"))
        with patch.dict(clipboard_formats.FORMAT_LIMITS, {"html": 3}):
            with self.assertRaises(ClipboardPayloadError):
                decode_clipboard_message(per_format)

        aggregate = self._message(
            ClipboardEntry("html", b"abc"),
            ClipboardEntry("rtf", b"def"),
        )
        with patch.object(clipboard_formats, "MAX_SNAPSHOT_BYTES", 5):
            with self.assertRaises(ClipboardPayloadError):
                decode_clipboard_message(aggregate)

    def test_decoder_bounds_highly_compressible_plaintext(self):
        compressed = base64.b64encode(zlib.compress(b"x" * 100)).decode("ascii")
        message = {
            "type": "clipboard_sync",
            "version": 2,
            "formats": [{"kind": "html", "raw_size": 3, "data": compressed}],
        }

        with patch.dict(clipboard_formats.FORMAT_LIMITS, {"html": 3}):
            with self.assertRaises(ClipboardPayloadError):
                decode_clipboard_message(message)

    def test_codec_enforces_encoded_message_limit(self):
        snapshot = ClipboardSnapshot([ClipboardEntry("html", b"html")])
        message = encode_clipboard_message(snapshot)
        encoded_size = len(
            json.dumps(message, separators=(",", ":")).encode("utf-8")
        )

        with patch.object(
            clipboard_formats, "MAX_ENCODED_MESSAGE_BYTES", encoded_size - 1
        ):
            with self.assertRaises(ClipboardPayloadError):
                encode_clipboard_message(snapshot)
            with self.assertRaises(ClipboardPayloadError):
                decode_clipboard_message(message)

    def test_validation_errors_do_not_echo_clipboard_content(self):
        secret = "PRIVATE-CONTENT-MARKER"
        message = self._message(ClipboardEntry("html", secret.encode("ascii")))
        message["formats"][0]["raw_size"] += 1

        with self.assertRaises(ClipboardPayloadError) as raised:
            decode_clipboard_message(message)

        self.assertNotIn(secret, str(raised.exception))

    def test_decoder_rejects_remaining_invalid_schema_shapes(self):
        valid = self._message(ClipboardEntry("html", b"html"))
        invalid_messages = []

        wrong_type = copy.deepcopy(valid)
        wrong_type["type"] = "other"
        invalid_messages.append(wrong_type)

        missing_field = copy.deepcopy(valid)
        del missing_field["version"]
        invalid_messages.append(missing_field)

        non_text_data = copy.deepcopy(valid)
        non_text_data["formats"][0]["data"] = b"bytes"
        invalid_messages.append(non_text_data)

        negative_size = copy.deepcopy(valid)
        negative_size["formats"][0]["raw_size"] = -1
        invalid_messages.append(negative_size)

        empty_formats = copy.deepcopy(valid)
        empty_formats["formats"] = []
        invalid_messages.append(empty_formats)

        too_many_formats = copy.deepcopy(valid)
        too_many_formats["formats"] *= 7
        invalid_messages.append(too_many_formats)

        for message in invalid_messages:
            with self.subTest(message=message):
                with self.assertRaises(ClipboardPayloadError):
                    decode_clipboard_message(message)


if __name__ == "__main__":
    unittest.main()
