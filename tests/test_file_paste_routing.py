import unittest

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


if __name__ == "__main__":
    unittest.main()
