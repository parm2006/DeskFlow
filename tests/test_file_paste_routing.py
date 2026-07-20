import unittest

from app.clipboard_offer import ClipboardKind, ClipboardOffer, RemoteClipboardState
from app.client import DeskFlowClient
from app.file_transfer.paste_coordinator import PasteCoordinator
from app.server import DeskFlowServer


class RecordingNetwork:
    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return True


class RecordingCoordinator:
    def __init__(self):
        self.values = []

    def set_remote_files_available(self, value):
        self.values.append(value)


class RecordingClipboard:
    def __init__(self):
        self.injected = []

    def inject(self, payload):
        self.injected.append(payload)


class FileAvailabilityRoutingTests(unittest.TestCase):
    def test_server_logs_file_offer_send_and_receive_boundaries(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.control_network = RecordingNetwork()
        server.paste_coordinator = RecordingCoordinator()

        with self.assertLogs("app.server", level="INFO") as logs:
            server.on_local_file_availability(False)
            server.on_remote_file_availability({"available": True})

        output = "\n".join(logs.output)
        self.assertIn("Server sending local file offer: available=false", output)
        self.assertIn("Server received remote file offer: available=true", output)

    def test_client_logs_file_offer_send_and_receive_boundaries(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.control_network = RecordingNetwork()
        client.paste_coordinator = RecordingCoordinator()

        with self.assertLogs("app.client", level="INFO") as logs:
            client.on_local_file_availability(False)
            client.on_remote_file_availability({"available": True})

        output = "\n".join(logs.output)
        self.assertIn("Client sending local file offer: available=false", output)
        self.assertIn("Client received remote file offer: available=true", output)

    def test_client_sends_local_boolean_and_applies_remote_boolean(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.control_network = RecordingNetwork()
        client.paste_coordinator = RecordingCoordinator()

        client.on_local_file_availability(True)
        client.on_remote_file_availability({"available": False})

        self.assertEqual(client.control_network.messages, [{"type": "file_clipboard_available", "available": True}])
        self.assertEqual(client.paste_coordinator.values, [False])

    def test_server_sends_local_boolean_and_applies_remote_boolean(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.control_network = RecordingNetwork()
        server.paste_coordinator = RecordingCoordinator()

        server.on_local_file_availability(False)
        server.on_remote_file_availability({"available": True})

        self.assertEqual(server.control_network.messages, [{"type": "file_clipboard_available", "available": False}])
        self.assertEqual(server.paste_coordinator.values, [True])


class ClipboardOfferRoutingTests(unittest.TestCase):
    def _client(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.control_network = RecordingNetwork()
        client.data_network = RecordingNetwork()
        client.paste_coordinator = RecordingCoordinator()
        client.clipboard = RecordingClipboard()
        client.is_active = True
        client.remote_clipboard_state = RemoteClipboardState()
        client.local_clipboard_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        client.current_clipboard_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        client.current_clipboard_origin = None
        return client

    def _server(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.control_network = RecordingNetwork()
        server.data_network = RecordingNetwork()
        server.paste_coordinator = RecordingCoordinator()
        server.clipboard = RecordingClipboard()
        server.switching_to_client = False
        server.remote_clipboard_state = RemoteClipboardState()
        server.local_clipboard_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        server.current_clipboard_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        server.current_clipboard_origin = None
        return server

    def test_local_offer_uses_control_lane_and_payload_carries_same_revision(self):
        client = self._client()
        offer = ClipboardOffer(ClipboardKind.ORDINARY, 4)

        client.on_local_clipboard_offer(offer)
        self.assertTrue(
            client._send_clipboard_snapshot(
                {"text": "latest", "_deskflow_offer_revision": 4}
            )
        )

        self.assertEqual(
            client.control_network.messages,
            [{"type": "clipboard_offer", "kind": "ordinary", "revision": 4}],
        )
        self.assertEqual(client.data_network.messages[0]["offer_revision"], 4)
        self.assertNotIn(
            "_deskflow_offer_revision", client.data_network.messages[0]
        )

    def test_data_arriving_before_control_waits_for_matching_offer(self):
        client = self._client()
        payload = {
            "type": "clipboard_sync",
            "offer_revision": 7,
            "text": "latest",
        }

        client.on_remote_copy(payload)
        self.assertEqual(client.clipboard.injected, [])
        client.on_remote_clipboard_offer(
            {"type": "clipboard_offer", "kind": "ordinary", "revision": 7}
        )

        self.assertEqual(client.clipboard.injected, [payload])
        self.assertEqual(client.paste_coordinator.values[-1], False)

    def test_delayed_ordinary_payload_cannot_replace_newer_file_offer(self):
        client = self._client()
        client.on_remote_clipboard_offer(
            {"type": "clipboard_offer", "kind": "ordinary", "revision": 8}
        )
        client.on_remote_clipboard_offer(
            {"type": "clipboard_offer", "kind": "files", "revision": 9}
        )

        client.on_remote_copy(
            {"type": "clipboard_sync", "offer_revision": 8, "text": "stale"}
        )

        self.assertEqual(client.clipboard.injected, [])
        self.assertEqual(client.paste_coordinator.values[-1], True)

    def test_new_local_ordinary_offer_immediately_clears_remote_file_interception(self):
        server = self._server()
        server.on_remote_clipboard_offer(
            {"type": "clipboard_offer", "kind": "files", "revision": 2}
        )
        self.assertEqual(server.paste_coordinator.values[-1], True)

        server.on_local_clipboard_offer(
            ClipboardOffer(ClipboardKind.ORDINARY, 1)
        )

        self.assertEqual(server.paste_coordinator.values[-1], False)

    def test_server_intercepts_files_only_when_offer_origin_is_other_screen(self):
        server = self._server()
        server.on_local_clipboard_offer(ClipboardOffer(ClipboardKind.FILES, 1))
        self.assertEqual(server.paste_coordinator.values[-1], False)

        server.switching_to_client = True
        server._apply_clipboard_interception()

        self.assertEqual(server.paste_coordinator.values[-1], True)

    def test_out_of_order_local_callback_cannot_roll_offer_revision_back(self):
        server = self._server()
        newest = ClipboardOffer(ClipboardKind.ORDINARY, 5)
        stale = ClipboardOffer(ClipboardKind.FILES, 4)

        self.assertTrue(server.on_local_clipboard_offer(newest))
        self.assertFalse(server.on_local_clipboard_offer(stale))

        self.assertEqual(server.current_clipboard_offer, newest)
        self.assertEqual(server.current_clipboard_origin, "local")
        self.assertEqual(
            server.control_network.messages,
            [{"type": "clipboard_offer", "kind": "ordinary", "revision": 5}],
        )

    def test_client_disconnect_clears_old_offer_and_accepts_new_session_revision(self):
        class Stoppable:
            def stop(self):
                return None

        client = self._client()
        client.paste_coordinator = PasteCoordinator(lambda: None)
        client.clipboard = Stoppable()
        client.clipboard_sender = Stoppable()
        client.hotkey_monitor = Stoppable()
        client.disconnect = lambda *args, **kwargs: True

        client.on_remote_clipboard_offer(
            {"type": "clipboard_offer", "kind": "files", "revision": 9}
        )
        self.assertTrue(client.paste_coordinator.remote_files_available)

        client.on_disconnected({})

        self.assertEqual(
            client.remote_clipboard_state.current,
            ClipboardOffer(ClipboardKind.UNKNOWN, 0),
        )
        self.assertIsNone(client.current_clipboard_origin)
        self.assertFalse(client.paste_coordinator.remote_files_available)

        client.is_active = True
        self.assertTrue(client.on_remote_clipboard_offer({
            "type": "clipboard_offer", "kind": "files", "revision": 1
        }))
        self.assertTrue(client.paste_coordinator.remote_files_available)


if __name__ == "__main__":
    unittest.main()
