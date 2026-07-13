import logging
import threading
import os
from pathlib import Path
from app.network import NetworkClient
from app.file_transfer.transport import FileLaneClient
from app.file_transfer.paste_coordinator import PasteCoordinator
from app.file_transfer.hotkey import WindowsPasteHotkeyMonitor
from app.file_transfer.paste_service import FilePasteService
from app.file_transfer.publisher import VirtualPastePublisher
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.selection import snapshot_selection
from app.file_transfer.sender import TransferSender
from app.file_transfer.controller import TransferController
from app.input_handler import InputHandler
from app.clipboard_handler import ClipboardHandler, encode_clipboard_snapshot
from app.latest_wins_sender import LatestWinsSender
from app.input_geometry import client_entry_position

logger = logging.getLogger(__name__)

class DeskFlowClient:
    def __init__(self, password, on_transfer_status=None, fingerprint_approval=None):
        self._fingerprint_approval = fingerprint_approval
        self._approved_fingerprint = None
        self.control_network = NetworkClient(password, fingerprint_approval=self._approve_fingerprint)
        self.data_network = NetworkClient(password, fingerprint_approval=self._approve_fingerprint)
        self.file_network = FileLaneClient()
        self.transfer_controller = TransferController()
        if on_transfer_status:
            self.transfer_controller.subscribe(on_transfer_status)
        self.file_receiver = TransferReceiver(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DeskFlow' / 'transfers' / 'client', controller=self.transfer_controller)
        self.file_receiver.attach(self.file_network)
        self.file_network.register_callback('cancel_request', self._on_cancel_request)
        self.file_network.register_callback('cancel_ack', self._on_cancel_ack)
        self.file_publisher = VirtualPastePublisher()
        self.input_handler = InputHandler()
        self.is_active = False
        self.control_connected = False
        self.data_connected = False
        
        # Setup control network callbacks
        self.control_network.register_callback('layout_config', self.on_layout_config)
        self.control_network.register_callback('ui_visibility', self.on_ui_visibility)
        self.control_network.register_callback('switch', self.on_switch)
        self.control_network.register_callback('mouse_move', self.on_mouse_move)
        self.control_network.register_callback('mouse_click', self.on_mouse_click)
        self.control_network.register_callback('mouse_scroll', self.on_mouse_scroll)
        self.control_network.register_callback('key_press', self.on_key_press)
        self.control_network.register_callback('key_release', self.on_key_release)
        self.control_network.register_callback('disconnected', self.on_disconnected)
        self.control_network.register_callback('file_lane_offer', self.on_file_lane_offer)
        self.control_network.register_callback('file_clipboard_available', self.on_remote_file_availability)
        self.control_network.register_callback('file_manifest_request', self.on_file_manifest_request)
        self.control_network.register_callback('file_manifest_response', self.on_file_manifest_response)
        self.control_network.register_callback('file_manifest_failed', self.on_file_manifest_failed)
        self.control_network.register_callback('file_manifest_ack', self.on_file_manifest_ack)
        self.control_network.register_callback('file_paste_trigger', lambda data: self.file_paste_service.request_paste())
        
        # Setup data network callbacks
        self.data_network.register_callback('clipboard_sync', self.on_remote_copy)
        self.data_network.register_callback('disconnected', self.on_disconnected)
        
        # Setup input callbacks
        self.input_handler.register_callback('client_edge_hit', self.on_client_edge_hit)

        # Setup clipboard
        self.clipboard = ClipboardHandler(
            on_clipboard_change=self.on_local_copy,
            on_file_availability=self.on_local_file_availability,
        )
        self.paste_coordinator = PasteCoordinator(self._request_remote_file_paste)
        self.hotkey_monitor = WindowsPasteHotkeyMonitor(self.paste_coordinator)
        self.file_paste_service = FilePasteService(
            self.control_network, self.file_receiver, self.file_publisher,
            TransferSender(self.file_network, controller=self.transfer_controller),
            lambda: snapshot_selection(self.clipboard.read_file_selection()),
        )
        self.clipboard_sender = LatestWinsSender(self._send_clipboard_snapshot)
        self.speed_scale_x = 1.0
        self.speed_scale_y = 1.0

    def _approve_fingerprint(self, fingerprint, host):
        """Approve a peer once and require both TLS lanes to use that identity."""
        if self._approved_fingerprint == fingerprint:
            return True
        if self._fingerprint_approval is None:
            return False
        approved = bool(self._fingerprint_approval(fingerprint, host))
        if approved:
            self._approved_fingerprint = fingerprint
        return approved

    def cancel_transfer(self, job_id):
        cancelled = self.transfer_controller.cancel(job_id)
        if cancelled:
            self.file_receiver.cancel_job(job_id)
            self.file_network.send({'type': 'cancel_request', 'job_id': job_id})
        return cancelled

    def _on_cancel_request(self, metadata, payload):
        job_id = metadata.get('job_id')
        self.transfer_controller.cancel(job_id)
        self.file_receiver.cancel_job(job_id)
        self.transfer_controller.confirm_cancelled(job_id)
        self.file_network.send({'type': 'cancel_ack', 'job_id': job_id})

    def _on_cancel_ack(self, metadata, payload):
        self.transfer_controller.confirm_cancelled(metadata.get('job_id'))

    def on_disconnected(self, data):
        logger.info("Disconnected from Server.")
        self.is_active = False
        self.clipboard.stop()
        self.clipboard_sender.stop()
        self.file_network.close()
        self.paste_coordinator.reset()
        self.hotkey_monitor.stop()

    def set_screen_size(self, w, h):
        self.input_handler.set_screen_size(w, h)

    def connect(self, host, port, callback):
        self.host = host
        self.control_connected = False
        self.data_connected = False
        self.connect_error = None
        callback_reported = False
        callback_lock = threading.Lock()

        def _report(success, error):
            nonlocal callback_reported
            if callback is None:
                return
            with callback_lock:
                if callback_reported:
                    return
                callback_reported = True
            callback(success, error)
        
        def _check_both_connected():
            if self.connect_error:
                return # Already errored out
            if self.control_connected and self.data_connected:
                self.clipboard.start()
                self.hotkey_monitor.start()
                _report(True, None)

        def _control_callback(success, err):
            if success:
                self.control_connected = True
                _check_both_connected()
            else:
                self.connect_error = err
                self.disconnect()
                _report(False, f"Control Socket Error: {err}")

        def _data_callback(success, err):
            if success:
                self.data_connected = True
                _check_both_connected()
            else:
                self.connect_error = err
                self.disconnect()
                _report(False, f"Data Socket Error: {err}")

        # Establish and approve the control lane first.  Pin its certificate
        # for the data lane so the two sockets cannot be paired to different
        # server identities during simultaneous TOFU.
        def _connect_data_after_control():
            fingerprint = self.control_network.peer_certificate_fingerprint()
            self.data_network.expected_fingerprint = fingerprint
            self.data_network.connect(host, port + 1, _data_callback)

        def _control_then_data(success, err):
            _control_callback(success, err)
            if success and not self.connect_error:
                _connect_data_after_control()

        self.control_network.connect(host, port, _control_then_data)

    def disconnect(self):
        self.control_network.disconnect()
        self.data_network.disconnect()
        self.file_network.close()

    def on_file_lane_offer(self, data):
        def connect_file_lane():
            try:
                self._connect_file_lane(data)
            except Exception as error:
                logger.error(f"Secure file lane connection failed: {error}")

        threading.Thread(target=connect_file_lane, daemon=True).start()

    def _connect_file_lane(self, data):
        port = data.get('port')
        token = data.get('token')
        if not isinstance(port, int) or not isinstance(token, str):
            raise ValueError("file-lane offer is malformed")
        fingerprint = self.control_network.peer_certificate_fingerprint()
        self.file_network.connect(self.host, port, fingerprint, token)

    def on_layout_config(self, data):
        server_pos = data.get('position', 'right')
        server_w = data.get('server_width', 1920)
        server_h = data.get('server_height', 1080)
        
        logger.info(f"Received layout config. Client is positioned at server's {server_pos} ({server_w}x{server_h})")
        
        # Calculate resolution scaling ratios
        client_w = self.input_handler.screen_width
        client_h = self.input_handler.screen_height
        
        self.speed_scale_x = client_w / server_w
        self.speed_scale_y = client_h / server_h
        logger.info(f"Resolution scaling factor calculated: X={self.speed_scale_x:.3f}, Y={self.speed_scale_y:.3f}")
        
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
        
        self.input_handler.inject_position(
            *client_entry_position(direction, w, h, ratio)
        )

    def set_ui_visibility(self, hidden):
        """Broadcast the requested GUI visibility to the connected server."""
        return self.control_network.send_message({
            'type': 'ui_visibility', 'hidden': bool(hidden)
        })

    def on_ui_visibility(self, data):
        callback = getattr(self, 'on_ui_visibility_changed', None)
        if callback:
            callback(bool(data.get('hidden', False)))

    def on_mouse_move(self, data):
        dx = data.get('dx', 0) * self.speed_scale_x
        dy = data.get('dy', 0) * self.speed_scale_y
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

    def on_local_copy(self, snapshot):
        return self.clipboard_sender.submit(snapshot)

    def _send_clipboard_snapshot(self, snapshot):
        payload = encode_clipboard_snapshot(snapshot)
        payload['type'] = 'clipboard_sync'
        return self.data_network.send_message(payload)

    def on_remote_copy(self, data):
        self.clipboard.inject(data)

    def on_local_file_availability(self, available):
        return self.control_network.send_message({
            'type': 'file_clipboard_available',
            'available': available is True,
        })

    def on_remote_file_availability(self, data):
        self.paste_coordinator.set_remote_files_available(data.get('available') is True)

    def _request_remote_file_paste(self):
        return self.file_paste_service.request_paste()

    def on_file_manifest_request(self, data):
        self.file_paste_service.on_manifest_request(data)

    def on_file_manifest_response(self, data):
        self.file_paste_service.on_manifest_response(data)

    def on_file_manifest_failed(self, data):
        self.file_paste_service.on_manifest_failed(data)

    def on_file_manifest_ack(self, data):
        self.file_paste_service.on_manifest_ack(data)
