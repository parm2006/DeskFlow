import unittest
from types import SimpleNamespace

from app.client import DeskFlowClient
from app.server import DeskFlowServer


class RecordingControl:
    def __init__(self):
        self.messages = []
        self.session_offer = SimpleNamespace(
            session_id="logical-session", file_token="file-token"
        )
        self.session_info = {
            "session_id": "logical-session", "file_token": "file-token"
        }

    def send_message(self, message):
        self.messages.append(message)
        return True

    def peer_certificate_fingerprint(self):
        return "a" * 64


class RecordingFileServer:
    port = 5002

    def __init__(self):
        self.offers = []

    def offer_session(self, token, session_id):
        self.offers.append((token, session_id))


class RecordingFileClient:
    def __init__(self):
        self.connections = []

    def connect(self, host, port, fingerprint, token, session_id=None):
        self.connections.append((host, port, fingerprint, token, session_id))


class FileLaneLifecycleTests(unittest.TestCase):
    def test_server_offers_one_use_file_session_over_control_lane(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.control_network = RecordingControl()
        server.file_network = RecordingFileServer()
        server.data_network = SimpleNamespace(session_id="logical-session")

        server._offer_file_lane()

        self.assertEqual(
            server.control_network.messages,
            [{"type": "file_lane_offer", "port": 5002, "session_id": "logical-session"}],
        )
        self.assertEqual(server.file_network.offers, [("file-token", "logical-session")])

    def test_client_binds_offer_to_live_control_certificate(self):
        client = DeskFlowClient.__new__(DeskFlowClient)
        client.host = "192.0.2.1"
        client.control_network = RecordingControl()
        client.file_network = RecordingFileClient()

        client.control_connected = False
        client.data_connected = False
        client._connect_file_lane({"port": 5002, "session_id": "logical-session"})

        self.assertEqual(
            client.file_network.connections,
            [("192.0.2.1", 5002, "a" * 64, "file-token", "logical-session")],
        )


if __name__ == "__main__":
    unittest.main()
