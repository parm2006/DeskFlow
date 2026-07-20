import unittest
import threading

from app.clipboard_authority import ClipboardAuthority, ClipboardKind, ClipboardOrigin
from app.client import DeskFlowClient
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

    def confirm_files_available(self, value):
        self.values.append(value)


class RecordingClipboard:
    def __init__(self, inject_result=True):
        self.inject_result = inject_result
        self.injected = []
        self.active_values = []

    def inject(self, payload):
        self.injected.append(payload)
        return self.inject_result

    def set_active(self, active):
        self.active_values.append(active)


class FileAvailabilityRoutingTests(unittest.TestCase):
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


class ClipboardAuthorityRoutingTests(unittest.TestCase):
    def _client(self, *, active=True, inject_result=True):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.is_active = active
        client.control_network = RecordingNetwork()
        client.clipboard_sender = None
        client.paste_coordinator = RecordingCoordinator()
        client.clipboard = RecordingClipboard(inject_result=inject_result)
        client.clipboard_authority = ClipboardAuthority(local_active=active)
        client._clipboard_authority_lock = threading.RLock()
        client.remote_files_available = False
        return client

    def _server(self, *, switching=False, inject_result=True):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.switching_to_client = switching
        server.control_network = RecordingNetwork()
        server.paste_coordinator = RecordingCoordinator()
        server.clipboard = RecordingClipboard(inject_result=inject_result)
        server.clipboard_authority = ClipboardAuthority(
            local_active=not switching
        )
        server._clipboard_authority_lock = threading.RLock()
        server.local_files_available = False
        server.remote_files_available = False
        return server

    def test_one_active_client_copy_claims_local_authority_and_sends_one_status(self):
        client = self._client(active=True)

        self.assertTrue(client.on_local_clipboard_kind(ClipboardKind.ORDINARY))

        self.assertEqual(client.clipboard_authority.origin, ClipboardOrigin.LOCAL)
        self.assertEqual(
            client.control_network.messages,
            [{"type": "file_clipboard_available", "available": False}],
        )
        self.assertEqual(client.paste_coordinator.values, [False])

    def test_inactive_client_copy_cannot_publish_or_claim_authority(self):
        client = self._client(active=False)

        self.assertFalse(client.on_local_clipboard_kind(ClipboardKind.FILES))

        self.assertEqual(client.clipboard_authority.origin, ClipboardOrigin.UNKNOWN)
        self.assertEqual(client.control_network.messages, [])

    def test_active_local_copy_rejects_delayed_remote_payload(self):
        client = self._client(active=True)
        client.clipboard_authority.note_local_copy(ClipboardKind.ORDINARY)
        payload = {"text": "stale", "type": "clipboard_sync"}

        self.assertFalse(client.on_remote_copy(payload))

        self.assertEqual(client.clipboard.injected, [])
        self.assertEqual(client.clipboard_authority.origin, ClipboardOrigin.LOCAL)

    def test_active_local_copy_rejects_delayed_remote_status(self):
        client = self._client(active=True)
        client.clipboard_authority.note_local_copy(ClipboardKind.ORDINARY)

        self.assertFalse(
            client.on_remote_file_availability({"available": True})
        )

        self.assertEqual(client.paste_coordinator.values, [])
        self.assertEqual(client.clipboard_authority.origin, ClipboardOrigin.LOCAL)

    def test_remote_status_then_payload_is_accepted_after_screen_switch(self):
        client = self._client(active=True)

        self.assertTrue(
            client.on_remote_file_availability({"available": False})
        )
        self.assertTrue(client.on_remote_copy({"text": "server copy"}))

        self.assertEqual(client.clipboard.injected, [{"text": "server copy"}])
        self.assertEqual(client.clipboard_authority.origin, ClipboardOrigin.REMOTE)
        self.assertEqual(client.clipboard_authority.kind, ClipboardKind.ORDINARY)

    def test_newer_remote_file_status_rejects_delayed_ordinary_payload(self):
        client = self._client(active=True)
        client.on_remote_file_availability({"available": True})

        self.assertFalse(client.on_remote_copy({"text": "stale text"}))

        self.assertEqual(client.clipboard.injected, [])
        self.assertEqual(client.clipboard_authority.kind, ClipboardKind.FILES)

    def test_server_rejects_delayed_ordinary_payload_after_file_status(self):
        server = self._server(switching=False)
        server.on_remote_file_availability({"available": True})

        self.assertFalse(server.on_remote_copy({"text": "stale text"}))

        self.assertEqual(server.clipboard.injected, [])
        self.assertEqual(server.clipboard_authority.kind, ClipboardKind.FILES)

    def test_inactive_client_keeps_physical_paste_native(self):
        client = self._client(active=False)

        self.assertTrue(
            client.on_remote_file_availability({"available": True})
        )

        self.assertTrue(client.remote_files_available)
        self.assertEqual(client.paste_coordinator.values, [False])

    def test_client_enables_remote_file_paste_only_after_control_switch(self):
        client = self._client(active=False)
        client.on_remote_file_availability({"available": True})

        client.is_active = True
        client._set_local_clipboard_active(True)

        self.assertEqual(client.paste_coordinator.values, [False, True])

    def test_accepted_remote_payload_claims_remote_authority(self):
        server = self._server(switching=True)
        payload = {"text": "client copy", "type": "clipboard_sync"}

        self.assertTrue(server.on_remote_copy(payload))

        self.assertEqual(server.clipboard.injected, [payload])
        self.assertEqual(server.clipboard_authority.origin, ClipboardOrigin.REMOTE)
        self.assertEqual(server.clipboard_authority.kind, ClipboardKind.ORDINARY)

    def test_rejected_injection_does_not_claim_remote_authority(self):
        server = self._server(switching=True, inject_result=False)

        self.assertFalse(server.on_remote_copy({"text": "rejected"}))

        self.assertEqual(server.clipboard_authority.origin, ClipboardOrigin.UNKNOWN)

    def test_disconnect_reset_clears_stale_authority_for_next_session(self):
        server = self._server(switching=False)
        server.clipboard_authority.note_local_copy(ClipboardKind.FILES)

        server._reset_clipboard_authority(local_active=True)

        self.assertEqual(server.clipboard_authority.origin, ClipboardOrigin.UNKNOWN)
        self.assertIsNone(server.clipboard_authority.kind)
        self.assertTrue(server.clipboard_authority.local_active)
        self.assertEqual(server.clipboard.active_values, [True])


if __name__ == "__main__":
    unittest.main()
