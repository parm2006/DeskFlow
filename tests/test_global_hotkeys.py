import unittest
from unittest.mock import Mock

from pynput.keyboard import KeyCode, Key

from app.global_hotkeys import GlobalHotkeyListener


class FakeListener:
    instances = []

    def __init__(self, on_press, on_release):
        self.on_press = on_press
        self.on_release = on_release
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class GlobalHotkeyTests(unittest.TestCase):
    def setUp(self):
        FakeListener.instances.clear()

    def test_shortcuts_invoke_callbacks_once_until_released(self):
        background, kill = Mock(), Mock()
        hotkeys = GlobalHotkeyListener(background, kill, listener_factory=FakeListener)
        self.assertTrue(hotkeys.start())
        listener = FakeListener.instances[0]
        for key in (Key.ctrl, Key.alt, Key.shift, KeyCode.from_char("b")):
            listener.on_press(key)
        listener.on_press(KeyCode.from_char("b"))
        background.assert_called_once_with()
        kill.assert_not_called()
        listener.on_release(KeyCode.from_char("b"))
        listener.on_press(KeyCode.from_char("b"))
        self.assertEqual(background.call_count, 2)

        for key in (Key.ctrl, Key.alt, Key.shift, Key.esc):
            listener.on_press(key)
        kill.assert_called_once_with()

    def test_start_stop_are_idempotent_and_clear_state(self):
        hotkeys = GlobalHotkeyListener(listener_factory=FakeListener)
        self.assertTrue(hotkeys.start())
        self.assertFalse(hotkeys.start())
        listener = FakeListener.instances[0]
        listener.on_press(Key.ctrl)
        self.assertTrue(hotkeys.stop())
        self.assertTrue(listener.stopped)
        self.assertFalse(hotkeys.stop())


if __name__ == "__main__":
    unittest.main()
