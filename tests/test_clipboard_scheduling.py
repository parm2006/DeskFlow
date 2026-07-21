import unittest
from unittest.mock import patch

from app.clipboard_handler import ClipboardHandler
from app.clipboard_formats import (
    ClipboardEntry,
    ClipboardPayloadError as V2ClipboardPayloadError,
    ClipboardSnapshot,
    decode_clipboard_message,
)
from app.client import DeskFlowClient
from app.server import DeskFlowServer
from app.windows_clipboard import ClipboardAccessError


class RecordingSender:
    def __init__(self):
        self.submitted = []

    def submit(self, payload):
        self.submitted.append(payload)
        return True


class RecordingNetwork:
    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return True


class FakeClipboardAdapter:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.capture_calls = 0

    def capture_open_clipboard(self):
        self.capture_calls += 1
        value = self.snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


class ClipboardSequenceTests(unittest.TestCase):
    def test_every_allowed_snapshot_kind_and_repeat_sequence_is_forwarded(self):
        same = ClipboardSnapshot([ClipboardEntry("html", b"same")])
        snapshots = [
            ClipboardSnapshot([ClipboardEntry("html", b"html")]),
            ClipboardSnapshot([ClipboardEntry("rtf", b"rtf")]),
            ClipboardSnapshot([ClipboardEntry("png", b"png")]),
            ClipboardSnapshot([ClipboardEntry("dibv5", b"dibv5")]),
            ClipboardSnapshot(
                [
                    ClipboardEntry("png", b"mixed-png"),
                    ClipboardEntry("html", b"mixed-html"),
                ]
            ),
            same,
            same,
        ]
        forwarded = []
        adapter = FakeClipboardAdapter(snapshots)
        handler = ClipboardHandler(forwarded.append, clipboard_adapter=adapter)

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
        ):
            for sequence in range(11, 18):
                handler._process_clipboard_sequence(sequence)

        self.assertEqual(forwarded, snapshots)
        self.assertEqual(adapter.capture_calls, len(snapshots))

    def test_file_sequence_skips_ordinary_capture(self):
        adapter = FakeClipboardAdapter(
            [ClipboardSnapshot([ClipboardEntry("html", b"fallback")])]
        )
        forwarded = []
        file_changes = []
        handler = ClipboardHandler(
            forwarded.append,
            on_file_availability=file_changes.append,
            clipboard_adapter=adapter,
        )

        with patch(
            "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
            return_value=True,
        ):
            handler._process_clipboard_sequence(11)

        self.assertEqual(file_changes, [True])
        self.assertEqual(forwarded, [])
        self.assertEqual(adapter.capture_calls, 0)

    def test_invalid_snapshot_is_rejected_once_without_lock_retries(self):
        adapter = FakeClipboardAdapter(
            [V2ClipboardPayloadError("PRIVATE-CONTENT-MARKER")]
        )
        handler = ClipboardHandler(lambda _snapshot: None, clipboard_adapter=adapter)

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch("app.clipboard_handler.time.sleep") as sleep,
            self.assertLogs("app.clipboard_handler", level="WARNING") as logs,
        ):
            self.assertIsNone(handler._read_clipboard())

        self.assertEqual(adapter.capture_calls, 1)
        sleep.assert_not_called()
        self.assertNotIn("PRIVATE-CONTENT-MARKER", " ".join(logs.output))

    def test_transient_open_failure_keeps_bounded_retry_behavior(self):
        snapshot = ClipboardSnapshot([ClipboardEntry("html", b"html")])
        adapter = FakeClipboardAdapter([snapshot])
        handler = ClipboardHandler(lambda _snapshot: None, clipboard_adapter=adapter)

        with (
            patch(
                "app.clipboard_handler.win32clipboard.OpenClipboard",
                side_effect=[OSError("locked"), OSError("locked"), None],
            ),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch("app.clipboard_handler.time.sleep") as sleep,
        ):
            self.assertEqual(handler._read_clipboard(), snapshot)

        self.assertEqual(adapter.capture_calls, 1)
        self.assertEqual(sleep.call_count, 2)

    def test_adapter_access_failure_is_not_retried_as_lock_contention(self):
        adapter = FakeClipboardAdapter(
            [ClipboardAccessError("PRIVATE-OPERATING-SYSTEM-DETAIL")]
        )
        handler = ClipboardHandler(lambda _snapshot: None, clipboard_adapter=adapter)

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch("app.clipboard_handler.time.sleep") as sleep,
            self.assertLogs("app.clipboard_handler", level="WARNING") as logs,
        ):
            self.assertIsNone(handler._read_clipboard())

        self.assertEqual(adapter.capture_calls, 1)
        sleep.assert_not_called()
        self.assertNotIn(
            "PRIVATE-OPERATING-SYSTEM-DETAIL",
            " ".join(logs.output),
        )


class PeerClipboardSchedulingTests(unittest.TestCase):
    def test_client_submits_snapshot_without_mutating_it(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.clipboard_sender = RecordingSender()
        snapshot = ClipboardSnapshot([ClipboardEntry("html", b"hello")])

        self.assertTrue(client.on_local_copy(snapshot))

        self.assertEqual(snapshot.entries[0].data, b"hello")
        self.assertEqual(
            client.clipboard_sender.submitted,
            [{"snapshot": snapshot}],
        )

    def test_server_submits_snapshot_without_mutating_it(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.clipboard_sender = RecordingSender()
        snapshot = ClipboardSnapshot([ClipboardEntry("png", b"png")])

        self.assertTrue(server.on_local_copy(snapshot))

        self.assertEqual(snapshot.entries[0].data, b"png")
        self.assertEqual(
            server.clipboard_sender.submitted,
            [{"snapshot": snapshot}],
        )

    def test_client_encodes_snapshot_and_preserves_message_type(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.data_network = RecordingNetwork()
        snapshot = ClipboardSnapshot([ClipboardEntry("dib", b"dib")])

        self.assertTrue(client._send_clipboard_snapshot({"snapshot": snapshot}))

        message = client.data_network.messages[0]
        self.assertEqual(decode_clipboard_message(message), snapshot)

    def test_server_encodes_snapshot_and_preserves_message_type(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.data_network = RecordingNetwork()
        snapshot = ClipboardSnapshot(
            [
                ClipboardEntry("png", b"png"),
                ClipboardEntry("html", b"<p>x</p>"),
            ]
        )

        self.assertTrue(server._send_clipboard_snapshot({"snapshot": snapshot}))

        message = server.data_network.messages[0]
        self.assertEqual(decode_clipboard_message(message), snapshot)


if __name__ == "__main__":
    unittest.main()
