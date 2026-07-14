import logging
import os
from pynput.mouse import Controller as MouseController, Listener as MouseListener, Button
from pynput.keyboard import Controller as KeyboardController, Listener as KeyboardListener, Key, KeyCode
from app.safe_errors import error_name

logger = logging.getLogger(__name__)


class WindowsSpecialKeyInjector:
    KEYEVENTF_KEYUP = 0x0002
    VIRTUAL_KEYS = {"delete": 0x2E}

    def __init__(self, user32=None):
        if user32 is None:
            import ctypes
            user32 = ctypes.windll.user32
        self.user32 = user32

    def press(self, name):
        return self._emit(name, 0)

    def release(self, name):
        return self._emit(name, self.KEYEVENTF_KEYUP)

    def _emit(self, name, flags):
        virtual_key = self.VIRTUAL_KEYS.get(name)
        if virtual_key is None:
            return False
        self.user32.keybd_event(virtual_key, 0, flags, 0)
        return True

class InputHandler:
    def __init__(self):
        self.mouse = MouseController()
        self.mouse_listener = None
        self.keyboard = KeyboardController()
        self.special_key_injector = (
            WindowsSpecialKeyInjector() if os.name == "nt" else None
        )
        self.keyboard_listener = None
        self.callbacks = {}
        
        self.is_captured = False
        self.screen_width = 1920 # Will be updated
        self.screen_height = 1080
        
        self.last_x = 0
        self.last_y = 0
        
        # For re-centering approach
        self.center_x = 0
        self.center_y = 0
        self.ignore_next_move = False
        
        # Spatial Layout Configuration
        self.server_edge = 'right'
        self.client_edge = 'left'

    def set_layout(self, server_edge=None, client_edge=None):
        if server_edge:
            self.server_edge = server_edge
        if client_edge:
            self.client_edge = client_edge

    def set_screen_size(self, w, h):
        self.screen_width = w
        self.screen_height = h
        self.center_x = w // 2
        self.center_y = h // 2

    def register_callback(self, event_type, cb):
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(cb)

    def trigger(self, event_type, *args):
        for cb in self.callbacks.get(event_type, []):
            try:
                cb(*args)
            except Exception as error:
                logger.error("Callback failed (%s)", error_name(error))

    def start_edge_detection(self, edge=None):
        if edge:
            self.server_edge = edge
        self.stop()
        self.is_captured = False
        self.mouse_listener = MouseListener(on_move=self._on_move_edge)
        self.mouse_listener.start()

    def start_capture(self):
        self.stop()
        self.is_captured = True
        self.last_x, self.last_y = self.mouse.position
        
        # We try to use a normal listener, and we will recenter the cursor 
        # so it doesn't leave the server screen or click things.
        # Alternatively, we just suppress it all. Let's try suppress=True first.
        self.mouse_listener = MouseListener(
            on_move=self._on_move_capture,
            on_click=self._on_click_capture,
            on_scroll=self._on_scroll_capture,
            suppress=True
        )
        self.mouse_listener.start()
        logger.info("Mouse capture started")

    def stop(self):
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None
        self.stop_keyboard_capture()
        self.is_captured = False

    def start_keyboard_capture(self):
        self.stop_keyboard_capture()
        self.keyboard_listener = KeyboardListener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            suppress=True
        )
        self.keyboard_listener.start()

    def stop_keyboard_capture(self):
        if self.keyboard_listener:
            self.keyboard_listener.stop()
            self.keyboard_listener = None

    def _on_move_edge(self, x, y):
        if self.server_edge == 'right' and x >= self.screen_width - 2:
            self.trigger('edge_hit', 'right', y / self.screen_height)
        elif self.server_edge == 'left' and x <= 0:
            self.trigger('edge_hit', 'left', y / self.screen_height)
        elif self.server_edge == 'top' and y <= 0:
            self.trigger('edge_hit', 'top', x / self.screen_width)
        elif self.server_edge == 'bottom' and y >= self.screen_height - 2:
            self.trigger('edge_hit', 'bottom', x / self.screen_width)

    def _on_move_capture(self, x, y):
        if not self.is_captured:
            return
            
        dx = x - self.last_x
        dy = y - self.last_y
        
        if dx != 0 or dy != 0:
            self.last_x = x
            self.last_y = y
            self.trigger('mouse_move', dx, dy)
            
            # Check if we hit the boundary of the virtual capture area
            # Meaning we should return to the server screen. 
            # Note: For strict 'suppress' capture without overlay, we'd check server_edge here too.
            # But since we use the Tkinter overlay for returning, we let the GUI overlay trigger the return 
            # OR we just rely on the injected client mouse hitting the edge on the client side.
            # Actually, the switch back is triggered purely by the Client hitting its edge (inject_move).
            pass

    def _on_click_capture(self, x, y, button, pressed):
        if not self.is_captured:
            return
        btn_name = button.name if hasattr(button, 'name') else str(button)
        self.trigger('mouse_click', btn_name, pressed)

    def _on_scroll_capture(self, x, y, dx, dy):
        if not self.is_captured:
            return
        self.trigger('mouse_scroll', dx, dy)

    def _on_key_press(self, key):
        self.trigger('key_press', self._serialize_key(key))

    def _on_key_release(self, key):
        self.trigger('key_release', self._serialize_key(key))

    def _serialize_key(self, key):
        if hasattr(key, 'char') and key.char is not None:
            return {'type': 'char', 'value': key.char}
        elif hasattr(key, 'name'):
            return {'type': 'special', 'value': key.name}
        elif hasattr(key, 'vk') and key.vk is not None:
            return {'type': 'vk', 'value': key.vk}
        else:
            return {'type': 'unknown', 'value': str(key)}

    # --- Methods for the Client side to simulate inputs ---
    
    def inject_move(self, dx, dy):
        self.mouse.move(dx, dy)
        # Check if client mouse hits its return edge to switch back to server
        x, y = self.mouse.position
        if self.client_edge == 'left' and x <= 0:
            self.trigger('client_edge_hit', 'left', y / self.screen_height)
        elif self.client_edge == 'right' and x >= self.screen_width - 2:
            self.trigger('client_edge_hit', 'right', y / self.screen_height)
        elif self.client_edge == 'top' and y <= 0:
            self.trigger('client_edge_hit', 'top', x / self.screen_width)
        elif self.client_edge == 'bottom' and y >= self.screen_height - 2:
            self.trigger('client_edge_hit', 'bottom', x / self.screen_width)

    def inject_position(self, x, y):
        self.mouse.position = (x, y)

    def inject_click(self, button_name, pressed):
        btn = getattr(Button, button_name, None)
        if btn:
            if pressed:
                self.mouse.press(btn)
            else:
                self.mouse.release(btn)

    def inject_scroll(self, dx, dy):
        self.mouse.scroll(dx, dy)

    def inject_key_press(self, key_data):
        if (
            key_data and key_data.get('type') == 'special'
            and self.special_key_injector is not None
            and self.special_key_injector.press(key_data.get('value'))
        ):
            return
        key = self._deserialize_key(key_data)
        if key:
            self.keyboard.press(key)

    def inject_key_release(self, key_data):
        if (
            key_data and key_data.get('type') == 'special'
            and self.special_key_injector is not None
            and self.special_key_injector.release(key_data.get('value'))
        ):
            return
        key = self._deserialize_key(key_data)
        if key:
            self.keyboard.release(key)

    def _deserialize_key(self, key_data):
        if not key_data: return None
        k_type = key_data.get('type')
        val = key_data.get('value')
        if k_type == 'char':
            return val
        elif k_type == 'special':
            return getattr(Key, val, None)
        elif k_type == 'vk':
            return KeyCode.from_vk(val)
        return None
