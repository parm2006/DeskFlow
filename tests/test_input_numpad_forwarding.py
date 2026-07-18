import unittest

from app.input_handler import InputHandler, WindowsSpecialKeyInjector


class RecordingUser32:
    def __init__(self):
        self.events = []

    def keybd_event(self, virtual_key, scan_code, flags, extra_info):
        self.events.append((virtual_key, scan_code, flags, extra_info))


class NumpadKey:
    def __init__(self, vk, char=None, scan=0, flags=0):
        self.vk = vk
        self.char = char
        self._scan = scan
        self._flags = flags


class RecordingKeyboard:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))


class NumpadForwardingTests(unittest.TestCase):
    def test_serializes_numpad_digits_decimal_and_operators_as_native_keys(self):
        handler = InputHandler.__new__(InputHandler)

        for vk in range(0x60, 0x70):
            with self.subTest(vk=vk):
                key = NumpadKey(vk, char="1", scan=vk - 0x40, flags=1 if vk == 0x6F else 0)
                self.assertEqual(
                    handler._serialize_key(key),
                    {
                        "type": "native_key",
                        "vk": vk,
                        "scan": vk - 0x40,
                        "extended": vk == 0x6F,
                    },
                )

    def test_native_injector_preserves_scan_extended_and_release_flags(self):
        user32 = RecordingUser32()
        injector = WindowsSpecialKeyInjector(user32)

        self.assertTrue(injector.emit_native(0x6F, 0x35, True, pressed=True))
        self.assertTrue(injector.emit_native(0x6F, 0x35, True, pressed=False))

        self.assertEqual(
            user32.events,
            [
                (0x6F, 0x35, 0x0001, 0),
                (0x6F, 0x35, 0x0001 | 0x0002, 0),
            ],
        )

    def test_handler_routes_valid_native_keys_without_pynput_fallback(self):
        user32 = RecordingUser32()
        handler = InputHandler.__new__(InputHandler)
        handler.keyboard = RecordingKeyboard()
        handler.special_key_injector = WindowsSpecialKeyInjector(user32)
        key = {"type": "native_key", "vk": 0x61, "scan": 0x4F, "extended": False}

        handler.inject_key_press(key)
        handler.inject_key_release(key)

        self.assertEqual(
            user32.events,
            [(0x61, 0x4F, 0, 0), (0x61, 0x4F, 0x0002, 0)],
        )
        self.assertEqual(handler.keyboard.events, [])

    def test_malformed_native_metadata_is_ignored(self):
        user32 = RecordingUser32()
        handler = InputHandler.__new__(InputHandler)
        handler.keyboard = RecordingKeyboard()
        handler.special_key_injector = WindowsSpecialKeyInjector(user32)

        handler.inject_key_press(
            {"type": "native_key", "vk": "97", "scan": -1, "extended": "no"}
        )

        self.assertEqual(user32.events, [])
        self.assertEqual(handler.keyboard.events, [])

    def test_numlock_off_navigation_remains_an_ordinary_special_key(self):
        handler = InputHandler.__new__(InputHandler)

        class NavigationKey:
            name = "end"

        self.assertEqual(
            handler._serialize_key(NavigationKey()),
            {"type": "special", "value": "end"},
        )


if __name__ == "__main__":
    unittest.main()
