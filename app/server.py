import logging
from app.network import NetworkServer
from app.input_handler import InputHandler
from app.clipboard_handler import ClipboardHandler

logger = logging.getLogger(__name__)

class DeskFlowServer:
    def __init__(self, password, port=5000, on_capture_start=None, on_capture_stop=None):
        self.network = NetworkServer(password, '0.0.0.0', port)
        self.input_handler = InputHandler()
        self.on_capture_start = on_capture_start
        self.on_capture_stop = on_capture_stop
        
        # Setup network callbacks
        self.network.register_callback('connected', self.on_client_connected)
        self.network.register_callback('disconnected', self.on_client_disconnected)
        self.network.register_callback('switch_back', self.on_switch_back)
        self.network.register_callback('clipboard_sync', self.on_remote_copy)
        
        # Setup input callbacks
        self.input_handler.register_callback('edge_hit', self.on_edge_hit)
        self.input_handler.register_callback('mouse_move', self.on_mouse_move)
        self.input_handler.register_callback('mouse_click', self.on_mouse_click)
        self.input_handler.register_callback('mouse_scroll', self.on_mouse_scroll)
        self.input_handler.register_callback('key_press', self.on_key_press)
        self.input_handler.register_callback('key_release', self.on_key_release)

        # Setup clipboard
        self.clipboard = ClipboardHandler(on_clipboard_change=self.on_local_copy)

    def set_screen_size(self, w, h):
        self.input_handler.set_screen_size(w, h)

    def start(self):
        return self.network.start()

    def stop(self):
        self.input_handler.stop()
        self.network.stop()

    def on_client_connected(self, data):
        logger.info("Client connected, starting edge detection.")
        self.input_handler.start_edge_detection()
        self.clipboard.start()

    def on_client_disconnected(self, data):
        logger.info("Client disconnected, stopping edge detection and wiping clipboard.")
        if self.on_capture_stop:
            self.on_capture_stop()
        self.input_handler.stop()
        self.clipboard.stop()

    def on_edge_hit(self, direction, y_ratio):
        if direction == 'right':
            logger.info("Right edge hit. Switching to client.")
            self.network.send_message({
                'type': 'switch',
                'direction': 'right',
                'y_ratio': y_ratio
            })
            self.input_handler.stop() # Stop edge detection
            self.input_handler.start_keyboard_capture()
            if self.on_capture_start:
                self.on_capture_start()
        elif direction == 'left':
            logger.info("Left edge hit while capturing. Switching back to server.")
            self.input_handler.stop_keyboard_capture()
            if self.on_capture_stop:
                self.on_capture_stop()
            self.input_handler.start_edge_detection()
            y = int(y_ratio * self.input_handler.screen_height)
            self.input_handler.inject_position(self.input_handler.screen_width - 10, y)

    def on_switch_back(self, data):
        # Client hit its left edge
        logger.info("Client signaled switch back.")
        y_ratio = data.get('y_ratio', 0.5)
        self.input_handler.stop_keyboard_capture()
        if self.on_capture_stop:
            self.on_capture_stop()
        self.input_handler.start_edge_detection()
        y = int(y_ratio * self.input_handler.screen_height)
        self.input_handler.inject_position(self.input_handler.screen_width - 10, y)

    def on_mouse_move(self, dx, dy):
        self.network.send_message({
            'type': 'mouse_move',
            'dx': dx,
            'dy': dy
        })

    def on_mouse_click(self, button_name, pressed):
        self.network.send_message({
            'type': 'mouse_click',
            'button': button_name,
            'pressed': pressed
        })

    def on_mouse_scroll(self, dx, dy):
        self.network.send_message({
            'type': 'mouse_scroll',
            'dx': dx,
            'dy': dy
        })

    def on_key_press(self, key_data):
        self.network.send_message({
            'type': 'key_press',
            'key': key_data
        })

    def on_key_release(self, key_data):
        self.network.send_message({
            'type': 'key_release',
            'key': key_data
        })

    def on_local_copy(self, text):
        self.network.send_message({
            'type': 'clipboard_sync',
            'text': text
        })

    def on_remote_copy(self, data):
        text = data.get('text', '')
        self.clipboard.inject(text)
