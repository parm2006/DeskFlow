import logging
from app.network import NetworkClient
from app.input_handler import InputHandler
from app.clipboard_handler import ClipboardHandler

logger = logging.getLogger(__name__)

class DeskFlowClient:
    def __init__(self, password):
        self.control_network = NetworkClient(password)
        self.data_network = NetworkClient(password)
        self.input_handler = InputHandler()
        self.is_active = False
        self.control_connected = False
        self.data_connected = False
        
        # Setup control network callbacks
        self.control_network.register_callback('layout_config', self.on_layout_config)
        self.control_network.register_callback('switch', self.on_switch)
        self.control_network.register_callback('mouse_move', self.on_mouse_move)
        self.control_network.register_callback('mouse_click', self.on_mouse_click)
        self.control_network.register_callback('mouse_scroll', self.on_mouse_scroll)
        self.control_network.register_callback('key_press', self.on_key_press)
        self.control_network.register_callback('key_release', self.on_key_release)
        self.control_network.register_callback('disconnected', self.on_disconnected)
        
        # Setup data network callbacks
        self.data_network.register_callback('clipboard_sync', self.on_remote_copy)
        self.data_network.register_callback('disconnected', self.on_disconnected)
        
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
        self.control_connected = False
        self.data_connected = False
        self.connect_error = None
        
        def _check_both_connected():
            if self.connect_error:
                return # Already errored out
            if self.control_connected and self.data_connected:
                self.clipboard.start()
                if callback: callback(True, None)

        def _control_callback(success, err):
            if success:
                self.control_connected = True
                _check_both_connected()
            else:
                self.connect_error = err
                self.disconnect()
                if callback: callback(False, f"Control Socket Error: {err}")

        def _data_callback(success, err):
            if success:
                self.data_connected = True
                _check_both_connected()
            else:
                self.connect_error = err
                self.disconnect()
                if callback and not self.control_connected: # Avoid double callback if both fail
                    callback(False, f"Data Socket Error: {err}")

        self.control_network.connect(host, port, _control_callback)
        self.data_network.connect(host, port + 1, _data_callback)

    def disconnect(self):
        self.control_network.disconnect()
        self.data_network.disconnect()

    def on_layout_config(self, data):
        server_pos = data.get('position', 'right')
        logger.info(f"Received layout config. Client is positioned at server's {server_pos}")
        
        # Calculate our return edge (opposite of our position relative to server)
        # If client is to the right of server, return edge is left.
        # If client is below server (bottom), return edge is top.
        opposites = {
            'right': 'left',
            'left': 'right',
            'top': 'bottom',
            'bottom': 'top'
        }
        return_edge = opposites.get(server_pos, 'left')
        self.input_handler.set_layout(server_edge=server_pos, client_edge=return_edge)

    def on_switch(self, data):
        logger.info("Server switched control to this client.")
        self.is_active = True
        direction = data.get('direction')
        ratio = data.get('ratio', 0.5)
        
        w = self.input_handler.screen_width
        h = self.input_handler.screen_height
        
        if direction == 'right':
            self.input_handler.inject_position(2, int(h * ratio))
        elif direction == 'left':
            self.input_handler.inject_position(w - 2, int(h * ratio))
        elif direction == 'top':
            self.input_handler.inject_position(int(w * ratio), h - 2)
        elif direction == 'bottom':
            self.input_handler.inject_position(int(w * ratio), 2)

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

    def on_client_edge_hit(self, direction, ratio):
        if not self.is_active:
            return
            
        if direction == self.input_handler.client_edge:
            logger.info(f"Hit {direction} edge. Sending switch_back to server.")
            self.is_active = False
            self.control_network.send_message({
                'type': 'switch_back',
                'ratio': ratio
            })

    def on_local_copy(self, payload):
        payload['type'] = 'clipboard_sync'
        self.data_network.send_message(payload)

    def on_remote_copy(self, data):
        self.clipboard.inject(data)
