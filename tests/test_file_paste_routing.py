import threading
import unittest
from types import SimpleNamespace

from app.client import DeskFlowClient
from app.clipboard_formats import ClipboardEntry, ClipboardSnapshot
from app.file_transfer.paste_coordinator import PasteCoordinator
from app.server import DeskFlowServer


class RecordingNetwork:
    def __init__(self):
        self.messages = []
        self.session_id = "session-a"
        self.session_info = {"session_id": "session-a"}

    def send_message(self, message):
        self.messages.append(message)
        return True


class RecordingCoordinator:
    def __init__(self):
        self.values = []
        self.local_offers = []
        self.peer_offers = []
        self.destinations = []

    def set_remote_files_available(self, value):
        self.values.append(value)

    def observe_local_offer(self, kind, revision, session_id):
        self.local_offers.append((kind, revision, session_id))
        return True

    def observe_peer_offer(self, kind, revision, session_id):
        self.peer_offers.append((kind, revision, session_id))
        return True

    def set_destination_is_local(self, value):
        self.destinations.append(value)


class RecordingInbox:
    def __init__(self):
        self.offers = []
        self.payloads = []
        self.local_offer_count = 0

    def receive_offer(self, kind, revision, session_id):
        self.offers.append((kind, revision, session_id))
        return True

    def receive_payload(self, payload):
        self.payloads.append(payload)
        return True

    def on_local_offer(self):
        self.local_offer_count += 1
        return True


class RecordingInputHandler:
    def __init__(self, events):
        self.events = events
        self.client_edge = "left"

    def stop_keyboard_capture(self):
        self.events.append("capture-stopped")

    def start_keyboard_capture(self):
        self.events.append("capture-started")

    def stop(self):
        self.events.append("input-stopped")

    def release_all_injected_keys(self):
        self.events.append("keys-released")


class PasteServiceState:
    def __init__(self, active):
        self.destination_paste_active = active


class BlockingPasteService(PasteServiceState):
    def __init__(self):
        super().__init__(active=False)
        self.request_started = threading.Event()
        self.finish_request = threading.Event()

    def request_paste(self):
        self.request_started.set()
        self.finish_request.wait(1)
        self.destination_paste_active = True
        return object()


class FileAvailabilityRoutingTests(unittest.TestCase):
    def test_ordinary_clipboard_payload_carries_the_offer_identity(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.control_network = RecordingNetwork()
        client.data_network = RecordingNetwork()
        snapshot = ClipboardSnapshot([
            ClipboardEntry("unicode_text", b"text")
        ])

        client._send_clipboard_snapshot({
            "snapshot": snapshot,
            "offer_revision": 7,
            "session_id": "session-a",
        })

        self.assertEqual(len(client.data_network.messages), 1)
        self.assertEqual(client.data_network.messages[0]["version"], 3)
        self.assertEqual(client.data_network.messages[0]["offer_revision"], 7)
        self.assertEqual(
            client.data_network.messages[0]["session_id"], "session-a"
        )

    def test_local_copy_latches_revision_before_async_send(self):
        submitted = []
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.control_network = RecordingNetwork()
        client.clipboard = SimpleNamespace(offer_revision=11)
        client.clipboard_sender = SimpleNamespace(
            submit=lambda work: submitted.append(work) or True
        )
        snapshot = object()

        client.on_local_copy(snapshot)

        self.assertEqual(submitted, [{
            "snapshot": snapshot,
            "offer_revision": 11,
            "session_id": "session-a",
        }])

    def test_client_sends_and_observes_revisioned_clipboard_offers(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.control_network = RecordingNetwork()
        client.paste_coordinator = RecordingCoordinator()
        client.remote_clipboard_inbox = RecordingInbox()

        client.on_local_clipboard_offer("files", 7)
        client.on_remote_clipboard_offer({
            "kind": "ordinary",
            "revision": 9,
            "session_id": "session-a",
        })

        self.assertEqual(client.control_network.messages, [{
            "type": "clipboard_offer",
            "kind": "files",
            "revision": 7,
            "session_id": "session-a",
        }])
        self.assertEqual(
            client.paste_coordinator.local_offers,
            [("files", 7, "session-a")],
        )
        self.assertEqual(
            client.remote_clipboard_inbox.offers,
            [("ordinary", 9, "session-a")],
        )
        self.assertEqual(client.remote_clipboard_inbox.local_offer_count, 1)

    def test_server_sends_and_observes_revisioned_clipboard_offers(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.control_network = RecordingNetwork()
        server.paste_coordinator = RecordingCoordinator()
        server.remote_clipboard_inbox = RecordingInbox()

        server.on_local_clipboard_offer("ordinary", 3)
        server.on_remote_clipboard_offer({
            "kind": "files",
            "revision": 4,
            "session_id": "session-a",
        })

        self.assertEqual(server.control_network.messages, [{
            "type": "clipboard_offer",
            "kind": "ordinary",
            "revision": 3,
            "session_id": "session-a",
        }])
        self.assertEqual(
            server.paste_coordinator.local_offers,
            [("ordinary", 3, "session-a")],
        )
        self.assertEqual(
            server.remote_clipboard_inbox.offers,
            [("files", 4, "session-a")],
        )
        self.assertEqual(server.remote_clipboard_inbox.local_offer_count, 1)

    def test_remote_clipboard_data_routes_through_revision_inbox(self):
        payload = {"type": "clipboard_sync"}
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.remote_clipboard_inbox = RecordingInbox()

        self.assertTrue(client.on_remote_copy(payload))

        self.assertEqual(client.remote_clipboard_inbox.payloads, [payload])

    def test_terminal_transfer_releases_the_pending_paste_route(self):
        coordinator = PasteCoordinator(lambda: object())
        coordinator.reset("session-a")
        coordinator.observe_peer_offer("files", 1, "session-a")
        coordinator.on_key_press("ctrl")
        coordinator.on_key_press("v")
        self.assertIsNotNone(coordinator.pending_paste)
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.paste_coordinator = coordinator

        client._on_internal_transfer_status(
            SimpleNamespace(is_terminal=False)
        )
        self.assertIsNotNone(coordinator.pending_paste)

        client._on_internal_transfer_status(
            SimpleNamespace(is_terminal=True)
        )
        self.assertIsNone(coordinator.pending_paste)

    def test_server_ignores_edge_crossing_while_local_paste_is_pending(self):
        events = []
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.input_handler = RecordingInputHandler(events)
        server.file_paste_service = PasteServiceState(active=True)
        server.switching_to_client = False
        server.local_files_available = True
        server.layout_position = "right"
        server.paste_coordinator = RecordingCoordinator()
        server.control_network = RecordingNetwork()
        server.on_capture_start = None

        server.on_edge_hit("right", 0.5)

        self.assertFalse(server.switching_to_client)
        self.assertEqual(server.control_network.messages, [])
        self.assertEqual(events, [])

    def test_client_ignores_return_edge_while_local_paste_is_pending(self):
        events = []
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.input_handler = RecordingInputHandler(events)
        client.file_paste_service = PasteServiceState(active=True)
        client.control_network = RecordingNetwork()
        client.is_active = True

        client.on_client_edge_hit("left", 0.5)

        self.assertTrue(client.is_active)
        self.assertEqual(client.control_network.messages, [])
        self.assertEqual(events, [])

    def test_server_edge_cannot_race_paste_destination_latching(self):
        events = []
        service = BlockingPasteService()
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.file_paste_service = service
        server.input_handler = RecordingInputHandler(events)
        server.switching_to_client = False
        server.local_files_available = True
        server.layout_position = "right"
        server.paste_coordinator = RecordingCoordinator()
        server.control_network = RecordingNetwork()
        server.on_capture_start = None

        paste = threading.Thread(target=server._request_remote_file_paste)
        crossing = threading.Thread(
            target=server.on_edge_hit,
            args=("right", 0.5),
        )
        paste.start()
        self.assertTrue(service.request_started.wait(1))
        crossing.start()
        crossing.join(0.05)

        self.assertTrue(crossing.is_alive())

        service.finish_request.set()
        paste.join(1)
        crossing.join(1)
        self.assertFalse(server.switching_to_client)
        self.assertEqual(server.control_network.messages, [])

    def test_client_edge_cannot_race_paste_destination_latching(self):
        events = []
        service = BlockingPasteService()
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.file_paste_service = service
        client.input_handler = RecordingInputHandler(events)
        client.control_network = RecordingNetwork()
        client.is_active = True

        paste = threading.Thread(target=client._request_remote_file_paste)
        crossing = threading.Thread(
            target=client.on_client_edge_hit,
            args=("left", 0.5),
        )
        paste.start()
        self.assertTrue(service.request_started.wait(1))
        crossing.start()
        crossing.join(0.05)

        self.assertTrue(crossing.is_alive())

        service.finish_request.set()
        paste.join(1)
        crossing.join(1)
        self.assertTrue(client.is_active)
        self.assertEqual(client.control_network.messages, [])


if __name__ == "__main__":
    unittest.main()
