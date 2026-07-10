import logging
from app.network import NetworkServer
from app.input_handler import InputHandler
from app.clipboard_handler import ClipboardHandler

logger = logging.getLogger(__name__)

class DeskFlowServer:
    def __init__(self, password, port=5000, layout_position='right', on_capture_start=None, on_capture_stop=None):
        self.layout_position = layout_position
        self.on_capture_start = on_capture_start
        self.on_capture_stop = on_capture_stop
        
        self.control_network = NetworkServer(password, '0.0.0.0', port)
        self.data_network = NetworkServer(password, '0.0.0.0', port + 1)
        self.input_handler = InputHandler()
        
        self.control_connected = False
        self.data_connected = False
        
        # Setup control network callbacks
        self.control_network.register_callback('connected', lambda d: self._on_socket_connected('control'))
        self.control_network.register_callback('disconnected', lambda d: self._on_socket_disconnected('control'))
        self.control_network.register_callback('switch_back', self.on_switch_back)
        
        # Setup data network callbacks
        self.data_network.register_callback('connected', lambda d: self._on_socket_connected('data'))
        self.data_network.register_callback('disconnected', lambda d: self._on_socket_disconnected('data'))
        self.data_network.register_callback('clipboard_sync', self.on_remote_copy)
        
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
        c_success = self.control_network.start()
        d_success = self.data_network.start()
        if c_success and d_success:
            return True
        self.stop()
        return False

    def stop(self):
        self.control_network.stop()
        self.data_network.stop()
        self.input_handler.stop()
        self.clipboard.stop()

    def _on_socket_connected(self, sock_type):
        if sock_type == 'control':
            self.control_connected = True
        elif sock_type == 'data':
            self.data_connected = True
            
        if self.control_connected and self.data_connected:
            self.on_client_connected()

    def _on_socket_disconnected(self, sock_type):
        if sock_type == 'control':
            self.control_connected = False
        elif sock_type == 'data':
            self.data_connected = False
            
        # If either disconnects, tear down both
        self.control_network.disconnect()
        self.data_network.disconnect()
        self.on_client_disconnected()

    def on_client_connected(self):
        logger.info(f"Client connected on both ports, starting edge detection for layout: {self.layout_position}")
        # Send handshake layout config over control
        self.control_network.send_message({
            'type': 'layout_config',
            'position': self.layout_position
        })
        self.input_handler.start_edge_detection(self.layout_position)
        self.clipboard.start()

    def on_client_disconnected(self):
        logger.info("Client disconnected, stopping edge detection and wiping clipboard.")
        if self.on_capture_stop:
            self.on_capture_stop()
        self.input_handler.stop()
        self.clipboard.stop()

    def on_edge_hit(self, direction, ratio):
        if direction == self.layout_position:
            logger.info(f"Hit {direction} edge. Switching to client.")
            self.control_network.send_message({
                'type': 'switch',
                'direction': direction,
                'ratio': ratio
            })
            self.input_handler.stop() # Stop edge detection
            self.input_handler.start_keyboard_capture()
            if self.on_capture_start:
                self.on_capture_start()

    def on_switch_back(self, data):
        # Client hit its return edge
        logger.info("Client signaled switch back.")
        ratio = data.get('ratio', 0.5)
        self.input_handler.stop_keyboard_capture()
        if self.on_capture_stop:
            self.on_capture_stop()
            
        # Warp the server mouse cleanly to the boundary
        w = self.input_handler.screen_width
        h = self.input_handler.screen_height
        if self.layout_position == 'right':
            self.input_handler.inject_position(w - 2, int(h * ratio))
        elif self.layout_position == 'left':
            self.input_handler.inject_position(2, int(h * ratio))
        elif self.layout_position == 'top':
            self.input_handler.inject_position(int(w * ratio), 2)
        elif self.layout_position == 'bottom':
            self.input_handler.inject_position(int(w * ratio), h - 2)
            
        self.input_handler.start_edge_detection(self.layout_position)

    def on_mouse_move(self, dx, dy):
        self.control_network.send_message({
            'type': 'mouse_move',
            'dx': dx,
            'dy': dy
        })

    def on_mouse_click(self, button, pressed):
        self.control_network.send_message({
            'type': 'mouse_click',
            'button': button,
            'pressed': pressed
        })

    def on_mouse_scroll(self, dx, dy):
        self.control_network.send_message({
            'type': 'mouse_scroll',
            'dx': dx,
            'dy': dy
        })

    def on_key_press(self, key_data):
        self.control_network.send_message({
            'type': 'key_press',
            'key': key_data
        })

    def on_key_release(self, key_data):
        self.control_network.send_message({
            'type': 'key_release',
            'key': key_data
        })

    def on_local_copy(self, payload):
        payload['type'] = 'clipboard_sync'
        self.data_network.send_message(payload)

    def on_remote_copy(self, data):
        self.clipboard.inject(data)
