class PasteCoordinator:
    CTRL_KEYS = frozenset(("ctrl", "ctrl_l", "ctrl_r"))

    def __init__(self, on_remote_file_paste):
        self.on_remote_file_paste = on_remote_file_paste
        self.remote_files_available = False
        self._pressed_ctrl = set()
        self._suppressing_v = False

    def set_remote_files_available(self, available):
        self.remote_files_available = available is True

    def on_key_press(self, key):
        if key in self.CTRL_KEYS:
            self._pressed_ctrl.add(key)
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
