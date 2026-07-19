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

    def test_switch_back_releases_forwarded_control_before_capture_stops(self):
        events = []

        class Network(RecordingNetwork):
            def send_message(self, message):
                events.append(("message", message))
                return super().send_message(message)

        class Input:
            screen_width = 1920
            screen_height = 1080

            def stop_keyboard_capture(self):
                events.append(("capture", "stopped"))

            def inject_position(self, x, y):
                events.append(("position", (x, y)))

            def start_edge_detection(self, edge):
                events.append(("edge", edge))

        server = DeskFlowServer.__new__(DeskFlowServer)
        server.switching_to_client = True
        server.remote_files_available = False
        server.pressed_keys = {"ctrl"}
        server.forwarded_keys = {
            ("special", "ctrl"): {"type": "special", "value": "ctrl"}
        }
        server.paste_coordinator = type(
            "Coordinator",
            (),
            {"set_remote_files_available": lambda self, value: None},
        )()
        server.control_network = Network()
        server.input_handler = Input()
        server.on_capture_stop = None
        server.layout_position = "right"

        server.on_switch_back({"ratio": 0.5})

        self.assertEqual(events[0][0:2], ("message", {
            "type": "key_release",
            "key": {"type": "special", "value": "ctrl"},
        }))
        self.assertEqual(events[1], ("capture", "stopped"))
        self.assertEqual(server.pressed_keys, set())
        self.assertEqual(server.forwarded_keys, {})


if __name__ == "__main__":
    unittest.main()
