import logging

from app.safe_errors import error_name


logger = logging.getLogger(__name__)


class PasteCoordinator:
    CTRL_KEYS = frozenset(("ctrl", "ctrl_l", "ctrl_r"))

    def __init__(self, on_remote_file_paste, refresh_before_paste=None):
        self.on_remote_file_paste = on_remote_file_paste
        self.refresh_before_paste = refresh_before_paste
        self.remote_files_available = False
        self._pressed_ctrl = set()
        self._suppressing_v = False

    def set_remote_files_available(self, available):
        next_available = available is True
        if next_available != self.remote_files_available:
            logger.info(
                "File-paste interception changed: enabled=%s",
                str(next_available).lower(),
            )
        self.remote_files_available = next_available

    def on_key_press(self, key):
        if key in self.CTRL_KEYS:
            self._pressed_ctrl.add(key)
            return False
        if key.lower() == "v" and self._pressed_ctrl:
            if self.refresh_before_paste is not None:
                try:
                    refresh_succeeded = self.refresh_before_paste()
                except Exception as error:
                    logger.error(
                        "Clipboard refresh before paste failed (%s)",
                        error_name(error),
                    )
                    refresh_succeeded = False
                if refresh_succeeded is False:
                    return False
            if not self.remote_files_available:
                return False
            if not self._suppressing_v:
                self._suppressing_v = True
                logger.info("Ctrl+V routed to remote file paste")
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
