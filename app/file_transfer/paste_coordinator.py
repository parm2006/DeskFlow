import time


class PasteCoordinator:
    CTRL_KEYS = frozenset(("ctrl", "ctrl_l", "ctrl_r"))

    def __init__(
        self,
        on_remote_file_paste,
        *,
        clock=time.monotonic,
        copy_pending_timeout=0.35,
    ):
        self.on_remote_file_paste = on_remote_file_paste
        self._clock = clock
        self._copy_pending_timeout = float(copy_pending_timeout)
        self.remote_files_available = False
        self._pressed_ctrl = set()
        self._suppressing_v = False
        self._copy_pending_until = None
        self._copy_pending_previous = False

    def set_remote_files_available(self, available):
        self.confirm_files_available(available)

    def confirm_files_available(self, available):
        self.remote_files_available = available is True
        self._copy_pending_until = None
        self._copy_pending_previous = self.remote_files_available

    @property
    def copy_pending(self):
        if self._copy_pending_until is None:
            return False
        if self._clock() >= self._copy_pending_until:
            self.remote_files_available = self._copy_pending_previous
            self._copy_pending_until = None
            return False
        return True

    def note_copy_intent(self):
        if not self.copy_pending:
            self._copy_pending_previous = self.remote_files_available
        self._copy_pending_until = self._clock() + self._copy_pending_timeout

    def on_key_press(self, key):
        if key in self.CTRL_KEYS:
            self._pressed_ctrl.add(key)
            return False
        if key.lower() == "c" and self._pressed_ctrl:
            self.note_copy_intent()
            return False
        if key.lower() == "v" and self._pressed_ctrl and self.copy_pending:
            return False
        if key.lower() == "v" and self._pressed_ctrl and self.remote_files_available:
            if not self._suppressing_v:
                self._suppressing_v = True
                self.on_remote_file_paste()
            return True
        return False

    def on_key_release(self, key):
        if key in self.CTRL_KEYS:
            self._pressed_ctrl.discard(key)
            return False
        if key.lower() == "v" and self._suppressing_v:
            self._suppressing_v = False
            return True
        return False

    def reset(self):
        self.remote_files_available = False
        self._pressed_ctrl.clear()
        self._suppressing_v = False
        self._copy_pending_until = None
        self._copy_pending_previous = False
