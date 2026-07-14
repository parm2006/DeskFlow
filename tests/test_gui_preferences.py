import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.gui import DeskFlowGUI, configure_main_window, restore_saved_role
from app.preferences import UserPreferences


class Button:
    def __init__(self):
        self.state = None

    def configure(self, **values):
        self.state = values.get("state", self.state)

    def pack(self, **values):
        return None

    def pack_forget(self):
        return None


class PreferencesTests(unittest.TestCase):
    def test_role_store_round_trips_only_supported_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            store = UserPreferences(Path(directory))
            self.assertIsNone(store.load_role())
            store.save_role("client")
            self.assertEqual(UserPreferences(Path(directory)).load_role(), "client")
            with self.assertRaises(ValueError):
                store.save_role("daemon")

    def test_corrupt_preferences_fall_back_without_exposing_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            path.write_text("private invalid data", encoding="utf-8")

            with self.assertLogs("app.preferences", level="ERROR") as logs:
                self.assertIsNone(UserPreferences(Path(directory)).load_role())
            self.assertNotIn("private invalid data", "\n".join(logs.output))


class SuccessfulRoleTimingTests(unittest.TestCase):
    def test_invalid_ports_show_actionable_status_without_starting_or_connecting(self):
        class Entry:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        statuses = []
        server_gui = DeskFlowGUI.__new__(DeskFlowGUI)
        server_gui.server_port_entry = Entry("not-a-port")
        server_gui.server_password_entry = Entry("secret")
        server_gui._set_status = lambda message, color: statuses.append((message, color))

        server_gui.start_server()

        client_gui = DeskFlowGUI.__new__(DeskFlowGUI)
        client_gui.client_ip_entry = Entry("192.0.2.1")
        client_gui.client_port_entry = Entry("70000")
        client_gui.client_password_entry = Entry("secret")
        client_gui._set_status = lambda message, color: statuses.append((message, color))

        client_gui.connect_client()

        self.assertEqual(
            statuses,
            [
                ("Status: Invalid port\nEnter a number from 1 to 65535.", "red"),
                ("Status: Invalid port\nEnter a number from 1 to 65535.", "red"),
            ],
        )

    def test_client_role_is_saved_only_after_successful_full_connection(self):
        roles = []
        source = object()
        gui = DeskFlowGUI.__new__(DeskFlowGUI)
        gui.client = source
        gui.preferences = type("Preferences", (), {"save_role": lambda self, role: roles.append(role)})()
        gui.client_connect_btn = Button()
        gui.client_disconnect_btn = Button()
        gui._set_status = lambda message, color: None
        gui.save_known_host = lambda ip, port: None

        gui._handle_connect_result(source, False, "Incorrect password", "host", 5000)
        self.assertEqual(roles, [])

        gui._handle_connect_result(source, True, None, "host", 5000)
        self.assertEqual(roles, ["client"])

    def test_unwritable_preferences_do_not_break_a_successful_connection(self):
        statuses = []
        source = object()
        gui = DeskFlowGUI.__new__(DeskFlowGUI)
        gui.client = source
        gui.preferences = type(
            "Preferences", (),
            {
                "save_role": lambda self, role: (_ for _ in ()).throw(
                    PermissionError("private path detail")
                )
            },
        )()
        gui.client_connect_btn = Button()
        gui.client_disconnect_btn = Button()
        gui._set_status = lambda message, color: statuses.append((message, color))
        gui.save_known_host = lambda ip, port: None

        with self.assertLogs("app.gui", level="ERROR") as logs:
            gui._handle_connect_result(source, True, None, "host", 5000)

        self.assertEqual(statuses, [("Status: Connected to host:5000", "green")])
        self.assertNotIn("private path detail", "\n".join(logs.output))

    def test_server_role_is_saved_only_after_listener_starts(self):
        roles = []
        statuses = []

        class Entry:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class Network:
            def register_callback(self, event, callback):
                return None

        class Server:
            def __init__(self, starts):
                self.starts = starts
                self.control_network = Network()
                self.identity = type("Identity", (), {"cert_path": "cert", "recovered": False})()

            def set_screen_size(self, width, height):
                return None

            def start(self):
                return self.starts

            def stop(self):
                return None

        gui = DeskFlowGUI.__new__(DeskFlowGUI)
        gui.server_port_entry = Entry("5000")
        gui.server_password_entry = Entry("secret")
        gui.server = None
        gui.overlay = object()
        gui.layout_position = "right"
        gui.show_overlay = lambda: None
        gui.hide_overlay = lambda: None
        gui._on_transfer_status = lambda status: None
        gui._on_server_client_connected = lambda data: None
        gui._on_server_client_disconnected = lambda data: None
        gui.winfo_screenwidth = lambda: 1920
        gui.winfo_screenheight = lambda: 1080
        gui._set_status = lambda message, color: statuses.append((message, color))
        gui.server_start_btn = Button()
        gui.server_stop_btn = Button()
        gui.preferences = type("Preferences", (), {"save_role": lambda self, role: roles.append(role)})()

        with patch("app.gui.DeskFlowServer", return_value=Server(False)):
            gui.start_server()
        self.assertEqual(roles, [])
        self.assertEqual(
            statuses[-1],
            (
                "Status: Could not start server\n"
                "Check whether the selected port is already in use.",
                "red",
            ),
        )

        with (
            patch("app.gui.DeskFlowServer", return_value=Server(True)),
            patch("app.gui.certificate_fingerprint", return_value="ab" * 32),
        ):
            gui.start_server()
        self.assertEqual(roles, ["server"])


class FixedWindowConfigurationTests(unittest.TestCase):
    def test_root_configuration_is_compact_fixed_and_non_maximizable(self):
        class Window:
            def __init__(self):
                self.geometry_value = None
                self.resizable_value = None

            def geometry(self, value):
                self.geometry_value = value

            def resizable(self, width, height):
                self.resizable_value = (width, height)

        window = Window()

        configure_main_window(window)

        self.assertEqual(window.geometry_value, "400x560")
        self.assertEqual(window.resizable_value, (False, False))

    def test_saved_role_selects_the_matching_tab_and_invalid_values_do_nothing(self):
        class Tabs:
            def __init__(self):
                self.selected = []

            def set(self, name):
                self.selected.append(name)

        tabs = Tabs()
        restore_saved_role(tabs, "client")
        restore_saved_role(tabs, "server")
        restore_saved_role(tabs, None)

        self.assertEqual(tabs.selected, ["Client", "Server (Host)"])


if __name__ == "__main__":
    unittest.main()
