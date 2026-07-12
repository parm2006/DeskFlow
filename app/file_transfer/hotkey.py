from pynput.keyboard import Listener as KeyboardListener


class WindowsPasteHotkeyMonitor:
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    VK_CONTROL = 0x11
    VK_LCONTROL = 0xA2
    VK_RCONTROL = 0xA3
    VK_V = 0x56
    LLKHF_INJECTED = 0x10

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.listener = None

    def start(self):
        if self.listener is not None:
            return
        self.listener = KeyboardListener(
            on_press=lambda key: None,
            on_release=lambda key: None,
            win32_event_filter=self.filter_event,
        )
        self.listener.start()

    def stop(self):
        listener, self.listener = self.listener, None
        if listener is not None:
            listener.stop()
        self.coordinator.reset()

    def filter_event(self, message, data):
        if data.flags & self.LLKHF_INJECTED:
            return True
        is_press = message in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN)
        is_release = message in (self.WM_KEYUP, self.WM_SYSKEYUP)
        if not is_press and not is_release:
            return True

        key = self._key_name(data.vkCode)
        if key is None:
            return True
        suppress = (
            self.coordinator.on_key_press(key)
            if is_press
            else self.coordinator.on_key_release(key)
        )
        if suppress and self.listener is not None:
            self.listener.suppress_event()
            return False
        return True

    def _key_name(self, vk_code):
        if vk_code == self.VK_LCONTROL:
            return "ctrl_l"
        if vk_code == self.VK_RCONTROL:
            return "ctrl_r"
        if vk_code == self.VK_CONTROL:
            return "ctrl"
        if vk_code == self.VK_V:
            return "v"
        return None
