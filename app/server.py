import logging
from app.network import NetworkServer
from app.input_handler import InputHandler

logger = logging.getLogger(__name__)

class DeskFlowServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.network = NetworkServer(host, port)
        self.input_handler = InputHandler()
        
        # Setup network callbacks
        self.network.register_callback('connected', self.on_client_connected)
        self.network.register_callback('disconnected', self.on_client_disconnected)
        self.network.register_callback('switch_back', self.on_switch_back)
        
        # Setup input callbacks
        self.input_handler.register_callback('edge_hit', self.on_edge_hit)
        self.input_handler.register_callback('mouse_move', self.on_mouse_move)
        self.input_handler.register_callback('mouse_click', self.on_mouse_click)
        self.input_handler.register_callback('mouse_scroll', self.on_mouse_scroll)

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

    def on_client_disconnected(self, data):
        logger.info("Client disconnected, stopping edge detection.")
        self.input_handler.stop()

    def on_edge_hit(self, direction, y):
        if direction == 'right':
            logger.info("Right edge hit. Switching to client.")
            self.network.send_message({
                'type': 'switch',
                'direction': 'right',
                'y': y
            })
            self.input_handler.start_capture()
        elif direction == 'left':
            logger.info("Left edge hit while capturing. Switching back to server.")
            self.input_handler.start_edge_detection()
            # Position cursor back at the right edge
            self.input_handler.inject_position(self.input_handler.screen_width - 10, y)

    def on_switch_back(self, data):
        # Client hit its left edge
        logger.info("Client signaled switch back.")
        y = data.get('y', self.input_handler.screen_height // 2)
        self.input_handler.start_edge_detection()
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
