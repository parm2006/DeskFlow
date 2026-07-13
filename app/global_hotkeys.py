"""Global emergency and background-mode shortcuts.

The listener is intentionally independent from DeskFlow's input capture.  It
therefore remains active while the application window is withdrawn and while
the normal keyboard capture is stopped.
"""

import logging
import threading

from pynput.keyboard import Key, Listener

logger = logging.getLogger(__name__)


class GlobalHotkeyListener:
    """Listen for DeskFlow's global control shortcuts.

    ``Ctrl+Alt+Shift+B`` invokes ``on_background_toggle`` and
    ``Ctrl+Alt+Shift+Escape`` invokes ``on_kill``.  Callbacks are invoked from
    pynput's listener thread and should marshal UI work to the main thread.
    """

    _MODIFIERS = frozenset(("ctrl", "alt", "shift"))

    def __init__(self, on_background_toggle=None, on_kill=None, listener_factory=Listener):
        self.on_background_toggle = on_background_toggle or (lambda: None)
        self.on_kill = on_kill or (lambda: None)
        self._listener_factory = listener_factory
        self._listener = None
        self._pressed = set()
        self._triggered = set()
        self._lock = threading.Lock()

    @staticmethod
    def _name(key):
        """Normalize pynput key values into stable names."""
        if isinstance(key, Key):
            return {
                Key.ctrl: "ctrl", Key.ctrl_l: "ctrl", Key.ctrl_r: "ctrl",
                Key.alt: "alt", Key.alt_l: "alt", Key.alt_r: "alt",
                Key.shift: "shift", Key.shift_l: "shift", Key.shift_r: "shift",
                Key.esc: "esc",
            }.get(key)
        char = getattr(key, "char", None)
        if char:
            return char.lower()
        return str(key).lower().replace("key.", "")

    def _on_press(self, key):
        name = self._name(key)
        if not name:
            return
        with self._lock:
            self._pressed.add(name)
            modifiers = self._MODIFIERS.issubset(self._pressed)
            action = None
            if modifiers and name in ("b", "esc") and name not in self._triggered:
                self._triggered.add(name)
                action = self.on_background_toggle if name == "b" else self.on_kill
        if action:
            try:
                action()
            except Exception:
                logger.exception("Global hotkey callback failed")

    def _on_release(self, key):
        name = self._name(key)
        if not name:
            return
        with self._lock:
            self._pressed.discard(name)
            if name in ("b", "esc") or not self._MODIFIERS.issubset(self._pressed):
                self._triggered.discard(name)

    def start(self):
        """Start listening; safe to call repeatedly."""
        with self._lock:
            if self._listener is not None:
                return False
            self._pressed.clear()
            self._triggered.clear()
            listener = self._listener_factory(on_press=self._on_press, on_release=self._on_release)
            self._listener = listener
        listener.start()
        return True

    def stop(self):
        """Stop listening and release all tracked key state."""
        with self._lock:
            listener, self._listener = self._listener, None
            self._pressed.clear()
            self._triggered.clear()
        if listener is not None:
            listener.stop()
            return True
        return False

