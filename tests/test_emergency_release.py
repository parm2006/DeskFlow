import unittest

from app.server import DeskFlowServer


class RecordingNetwork:
    def __init__(self):
        self.messages = []
        self.disconnected = False

    def send_message(self, message):
        self.messages.append(message)
        return True

    def disconnect(self):
        self.disconnected = True


class Coordinator:
    def on_key_press(self, value):
        return False


class EmergencyReleaseTests(unittest.TestCase):
    def test_emergency_exit_releases_forwarded_modifiers_before_disconnect(self):
        server = DeskFlowServer.__new__(DeskFlowServer)
        server.pressed_keys = {"ctrl", "alt", "shift"}
        server.paste_coordinator = Coordinator()
        server.control_network = RecordingNetwork()
        server.data_network = RecordingNetwork()

        server.on_key_press({"type": "special", "value": "esc"})

        released = [
            message["key"]["value"]
            for message in server.control_network.messages
            if message["type"] == "key_release"
        ]
        self.assertEqual(released, ["alt", "ctrl", "shift"])
        self.assertTrue(server.control_network.disconnected)


if __name__ == "__main__":
    unittest.main()
