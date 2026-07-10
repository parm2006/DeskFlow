import logging
from app.network import NetworkClient
from app.input_handler import InputHandler
from app.clipboard_handler import ClipboardHandler

logger = logging.getLogger(__name__)

class DeskFlowClient:
    def __init__(self, password):
        self.network = NetworkClient(password)
        self.input_handler = InputHandler()
        self.is_active = False
        
        # Setup network callbacks
        self.network.register_callback('switch', self.on_switch)
        self.network.register_callback('mouse_move', self.on_mouse_move)
        self.network.register_callback('mouse_click', self.on_mouse_click)
        self.network.register_callback('mouse_scroll', self.on_mouse_scroll)
        self.network.register_callback('key_press', self.on_key_press)
        self.network.register_callback('key_release', self.on_key_release)
        self.network.register_callback('disconnected', self.on_disconnected)
        self.network.register_callback('clipboard_sync', self.on_remote_copy)
        
        # Setup input callbacks
        self.input_handler.register_callback('client_edge_hit', self.on_client_edge_hit)

        # Setup clipboard
        self.clipboard = ClipboardHandler(on_clipboard_change=self.on_local_copy)

    def on_disconnected(self, data):
        logger.info("Disconnected from Server.")
        self.is_active = False
        self.clipboard.stop()

    def set_screen_size(self, w, h):
        self.input_handler.set_screen_size(w, h)

    def connect(self, host, port, callback):
        def _connect_callback(success, err):
            if success:
                self.clipboard.start()
            if callback:
                callback(success, err)
        self.network.connect(host, port, _connect_callback)

    def disconnect(self):
        self.network.disconnect()

    def on_switch(self, data):
        logger.info("Server switched control to this client.")
        self.is_active = True
        direction = data.get('direction')
        y_ratio = data.get('y_ratio', 0.5)
        
        y = int(y_ratio * self.input_handler.screen_height)
        
        if direction == 'right':
            # Cursor came from the right edge of the server, so it enters on the left edge of the client
            self.input_handler.inject_position(10, y)

    def on_mouse_move(self, data):
        dx = data.get('dx', 0)
        dy = data.get('dy', 0)
        self.input_handler.inject_move(dx, dy)

    def on_mouse_click(self, data):
        button_name = data.get('button')
        pressed = data.get('pressed')
        self.input_handler.inject_click(button_name, pressed)

    def on_mouse_scroll(self, data):
        dx = data.get('dx', 0)
        dy = data.get('dy', 0)
        self.input_handler.inject_scroll(dx, dy)

    def on_key_press(self, data):
        key_data = data.get('key')
        if key_data:
            self.input_handler.inject_key_press(key_data)

    def on_key_release(self, data):
        key_data = data.get('key')
        if key_data:
            self.input_handler.inject_key_release(key_data)

    def on_client_edge_hit(self, direction, y_ratio):
        if not self.is_active:
            return
            
        if direction == 'left':
            logger.info("Hit left edge. Sending switch_back to server.")
            self.is_active = False
            self.network.send_message({
                'type': 'switch_back',
                'y_ratio': y_ratio
            })

    def on_local_copy(self, text):
        self.network.send_message({
            'type': 'clipboard_sync',
            'text': text
        })

    def on_remote_copy(self, data):
        text = data.get('text', '')
        self.clipboard.inject(text)
