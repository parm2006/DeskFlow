import base64
import unittest
import zlib

from app.clipboard_handler import (
    ClipboardPayloadError,
    decode_compressed_clipboard_value,
    encode_clipboard_snapshot,
)
from app.client import DeskFlowClient
from app.server import DeskFlowServer
from app.latest_wins_sender import LatestWinsSender


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


class ClipboardEncodingTests(unittest.TestCase):
    def test_compressed_clipboard_decode_enforces_plaintext_limit(self):
        limit = 1024
        encoded = base64.b64encode(zlib.compress(b"x" * (limit + 1))).decode("ascii")

        with self.assertRaises(ClipboardPayloadError):
            decode_compressed_clipboard_value(encoded, limit)

    def test_compressed_clipboard_decode_rejects_trailing_or_invalid_data(self):
        encoded = base64.b64encode(zlib.compress(b"safe") + b"trailing").decode("ascii")

        with self.assertRaises(ClipboardPayloadError):
            decode_compressed_clipboard_value(encoded, 1024)
        with self.assertRaises(ClipboardPayloadError):
            decode_compressed_clipboard_value("not valid base64!", 1024)

    def test_compressed_clipboard_decode_accepts_bounded_payload(self):
        encoded = base64.b64encode(zlib.compress(b"safe")).decode("ascii")

        self.assertEqual(
            decode_compressed_clipboard_value(encoded, 4), b"safe"
        )

    def test_encode_snapshot_preserves_rich_clipboard_wire_schema(self):
        snapshot = {
            "text": "hello",
            "image": b"dib-bytes",
            "html": b"<b>hello</b>",
            "rtf": b"{\\rtf1 hello}",
        }

        payload = encode_clipboard_snapshot(snapshot)

        self.assertEqual(payload["text"], "hello")
        self.assertEqual(zlib.decompress(base64.b64decode(payload["image"])), b"dib-bytes")
        self.assertEqual(zlib.decompress(base64.b64decode(payload["html"])), b"<b>hello</b>")
        self.assertEqual(zlib.decompress(base64.b64decode(payload["rtf"])), b"{\\rtf1 hello}")
        self.assertEqual(set(payload), {"text", "image", "html", "rtf"})

    def test_encode_empty_snapshot_explicitly_replaces_remote_clipboard(self):
        self.assertEqual(
            encode_clipboard_snapshot({"_deskflow_offer_revision": 3}),
            {"empty": True},
        )


class PeerClipboardSchedulingTests(unittest.TestCase):
    def test_client_recreates_stopped_clipboard_sender_before_reconnect(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        stopped = LatestWinsSender(lambda payload: True)
        stopped.stop()
        client.clipboard_sender = stopped

        client._ensure_clipboard_sender()
        self.addCleanup(client.clipboard_sender.stop)

        self.assertIsNot(client.clipboard_sender, stopped)
        self.assertFalse(client.clipboard_sender.stopped)

    def test_client_submits_snapshot_without_mutating_it(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.clipboard_sender = RecordingSender()
        snapshot = {"text": "hello"}

        self.assertTrue(client.on_local_copy(snapshot))

        self.assertEqual(snapshot, {"text": "hello"})
        self.assertEqual(client.clipboard_sender.submitted, [{"text": "hello"}])

    def test_server_submits_snapshot_without_mutating_it(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.clipboard_sender = RecordingSender()
        snapshot = {"text": "hello"}

        self.assertTrue(server.on_local_copy(snapshot))

        self.assertEqual(snapshot, {"text": "hello"})
        self.assertEqual(server.clipboard_sender.submitted, [{"text": "hello"}])

    def test_client_encodes_snapshot_and_preserves_message_type(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.data_network = RecordingNetwork()

        self.assertTrue(client._send_clipboard_snapshot({"image": b"dib"}))

        message = client.data_network.messages[0]
        self.assertEqual(message["type"], "clipboard_sync")
        self.assertEqual(zlib.decompress(base64.b64decode(message["image"])), b"dib")

    def test_server_encodes_snapshot_and_preserves_message_type(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.data_network = RecordingNetwork()

        self.assertTrue(server._send_clipboard_snapshot({"html": b"<p>x</p>"}))

        message = server.data_network.messages[0]
        self.assertEqual(message["type"], "clipboard_sync")
        self.assertEqual(zlib.decompress(base64.b64decode(message["html"])), b"<p>x</p>")


if __name__ == "__main__":
    unittest.main()
