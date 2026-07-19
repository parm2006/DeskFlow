import unittest

from app.input_handler import InputHandler, WindowsSpecialKeyInjector


class RecordingUser32:
    def __init__(self):
        self.events = []

    def keybd_event(self, virtual_key, scan_code, flags, extra_info):
        self.events.append((virtual_key, scan_code, flags, extra_info))


class RecordingKeyboard:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))


class DeleteForwardingTests(unittest.TestCase):
    def test_shutdown_releases_every_locally_injected_key(self):
        handler = InputHandler.__new__(InputHandler)
        handler.keyboard = RecordingKeyboard()
        handler.special_key_injector = None

        handler.inject_key_press({"type": "special", "value": "ctrl"})
        handler.inject_key_press({"type": "char", "value": "d"})
        handler.release_all_injected_keys()

        self.assertEqual(
            [event[0] for event in handler.keyboard.events],
            ["press", "press", "release", "release"],
        )

    def test_windows_delete_injector_emits_native_press_and_release(self):
        user32 = RecordingUser32()
        injector = WindowsSpecialKeyInjector(user32)

        self.assertTrue(injector.press("delete"))
        self.assertTrue(injector.release("delete"))

        self.assertEqual(
            user32.events,
            [(0x2E, 0, 0, 0), (0x2E, 0, 0x0002, 0)],
        )

    def test_input_handler_routes_delete_to_native_injector_only(self):
        class Injector:
            def __init__(self):
                self.events = []

            def press(self, name):
                self.events.append(("press", name))
                return name == "delete"

            def release(self, name):
                self.events.append(("release", name))
                return name == "delete"

        handler = InputHandler.__new__(InputHandler)
        handler.keyboard = RecordingKeyboard()
        handler.special_key_injector = Injector()

        handler.inject_key_press({"type": "special", "value": "delete"})
        handler.inject_key_release({"type": "special", "value": "delete"})

        self.assertEqual(
            handler.special_key_injector.events,
            [("press", "delete"), ("release", "delete")],
        )
        self.assertEqual(handler.keyboard.events, [])


if __name__ == "__main__":
    unittest.main()
