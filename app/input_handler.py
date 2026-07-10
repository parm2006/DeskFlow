import logging
from pynput.mouse import Controller, Listener, Button

logger = logging.getLogger(__name__)

class InputHandler:
    def __init__(self):
        self.mouse = Controller()
        self.mouse_listener = None
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
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def start_edge_detection(self):
        self.stop()
        self.is_captured = False
        self.mouse_listener = Listener(on_move=self._on_move_edge)
        self.mouse_listener.start()

    def start_capture(self):
        self.stop()
        self.is_captured = True
        self.last_x, self.last_y = self.mouse.position
        
        # We try to use a normal listener, and we will recenter the cursor 
        # so it doesn't leave the server screen or click things.
        # Alternatively, we just suppress it all. Let's try suppress=True first.
        self.mouse_listener = Listener(
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
        self.is_captured = False

    def _on_move_edge(self, x, y):
        # Trigger if we hit the right edge
        if x >= self.screen_width - 2:
            y_ratio = y / self.screen_height
            self.trigger('edge_hit', 'right', y_ratio)
            
        # Trigger if we hit left edge
        if x <= 0:
            y_ratio = y / self.screen_height
            self.trigger('edge_hit', 'left', y_ratio)

    def _on_move_capture(self, x, y):
        if not self.is_captured:
            return
            
        dx = x - self.last_x
        dy = y - self.last_y
        
        if dx != 0 or dy != 0:
            self.last_x = x
            self.last_y = y
            self.trigger('mouse_move', dx, dy)
            
            # Check if we hit the left edge of the virtual capture area
            # Meaning we should return to the server screen
            if x <= 0:
                self.trigger('edge_hit', 'left', y)

    def _on_click_capture(self, x, y, button, pressed):
        if not self.is_captured:
            return
        btn_name = button.name if hasattr(button, 'name') else str(button)
        self.trigger('mouse_click', btn_name, pressed)

    def _on_scroll_capture(self, x, y, dx, dy):
        if not self.is_captured:
            return
        self.trigger('mouse_scroll', dx, dy)

    # --- Methods for the Client side to simulate inputs ---
    
    def inject_move(self, dx, dy):
        self.mouse.move(dx, dy)
        # Check if client mouse hits left edge to return to server
        x, y = self.mouse.position
        if x <= 0:
            y_ratio = y / self.screen_height
            self.trigger('client_edge_hit', 'left', y_ratio)

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
