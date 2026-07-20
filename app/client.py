import logging
import threading
import os
from pathlib import Path
from app.network import NetworkClient
from app.trust import PeerTrustStore
from app.file_transfer.transport import FileLaneClient
from app.file_transfer.paste_coordinator import PasteCoordinator
from app.file_transfer.hotkey import WindowsPasteHotkeyMonitor
from app.file_transfer.paste_service import FilePasteService
from app.file_transfer.publisher import VirtualPastePublisher
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.selection import snapshot_selection
from app.file_transfer.sender import TransferSender
from app.file_transfer.controller import TransferController
from app.file_transfer.cancellation import TransferCancellation
from app.input_handler import InputHandler
from app.clipboard_handler import ClipboardHandler, encode_clipboard_snapshot
from app.clipboard_offer import (
    ClipboardKind,
    ClipboardOffer,
    RemoteClipboardState,
)
from app.latest_wins_sender import LatestWinsSender
from app.input_geometry import client_entry_position
from app.safe_errors import error_name, public_error_message

logger = logging.getLogger(__name__)

class DeskFlowClient:
    def __init__(
        self, password, on_transfer_status=None, fingerprint_approval=None,
        trust_store=None, lane_timeout=10.0,
    ):
        self.password = password
        self.trust_store = trust_store or PeerTrustStore()
        self.fingerprint_approval = fingerprint_approval
        self.lane_timeout = float(lane_timeout)
        self.control_network = NetworkClient(
            password, role='control', trust_store=self.trust_store,
            fingerprint_approval=fingerprint_approval,
        )
        self.data_network = None
        self.file_network = FileLaneClient()
        self.transfer_controller = TransferController()
        if on_transfer_status:
            self.transfer_controller.subscribe(on_transfer_status)
        self.file_receiver = TransferReceiver(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'DeskFlow' / 'transfers' / 'client', controller=self.transfer_controller)
        self.file_receiver.attach(self.file_network)
        self.transfer_cancellation = TransferCancellation(
            self.file_network, self.transfer_controller, self.file_receiver
        )
        self.file_network.register_callback(
            'disconnected', lambda metadata, payload: self.on_disconnected(metadata)
        )
        self.file_publisher = VirtualPastePublisher()
        self.input_handler = InputHandler()
        self.is_active = False
        self.control_connected = False
        self.data_connected = False
        self._disconnecting = False
        
        # Setup control network callbacks
        self.control_network.register_callback('layout_config', self.on_layout_config)
        self.control_network.register_callback('switch', self.on_switch)
        self.control_network.register_callback('mouse_move', self.on_mouse_move)
        self.control_network.register_callback('mouse_click', self.on_mouse_click)
        self.control_network.register_callback('mouse_scroll', self.on_mouse_scroll)
        self.control_network.register_callback('key_press', self.on_key_press)
        self.control_network.register_callback('key_release', self.on_key_release)
        self.control_network.register_callback('disconnected', self.on_disconnected)
        self.control_network.register_callback('file_lane_offer', self.on_file_lane_offer)
        self.control_network.register_callback('clipboard_offer', self.on_remote_clipboard_offer)
        self.control_network.register_callback('file_clipboard_available', self.on_remote_file_availability)
        self.control_network.register_callback('file_manifest_request', self.on_file_manifest_request)
        self.control_network.register_callback('file_manifest_response', self.on_file_manifest_response)
        self.control_network.register_callback('file_manifest_failed', self.on_file_manifest_failed)
        self.control_network.register_callback('file_manifest_ack', self.on_file_manifest_ack)
        self.control_network.register_callback('file_paste_trigger', lambda data: self.file_paste_service.request_paste())
        
        # Setup data network callbacks
        # Setup input callbacks
        self.input_handler.register_callback('client_edge_hit', self.on_client_edge_hit)

        # Setup clipboard
        self._clipboard_offer_lock = threading.RLock()
        self.remote_clipboard_state = RemoteClipboardState()
        self.local_clipboard_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        self.current_clipboard_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        self.current_clipboard_origin = None
        self.clipboard = ClipboardHandler(
            on_clipboard_change=self.on_local_copy,
            on_clipboard_offer=self.on_local_clipboard_offer,
        )
        self.paste_coordinator = PasteCoordinator(
            self._request_remote_file_paste,
            refresh_before_paste=self._refresh_clipboard_before_paste,
        )
        self.hotkey_monitor = WindowsPasteHotkeyMonitor(self.paste_coordinator)
        self.file_paste_service = FilePasteService(
            self.control_network, self.file_receiver, self.file_publisher,
            TransferSender(self.file_network, controller=self.transfer_controller),
            lambda: snapshot_selection(self.clipboard.read_file_selection()),
            controller=self.transfer_controller,
        )
        self.clipboard_sender = LatestWinsSender(self._send_clipboard_snapshot)
        self.speed_scale_x = 1.0
        self.speed_scale_y = 1.0

    def cancel_transfer(self, job_id):
        return self.transfer_cancellation.request(job_id)

    def on_disconnected(self, data):
        logger.info("Disconnected from Server.")
        report_setup_failure = False
        internal_disconnect = False
        if hasattr(self, '_connect_lock'):
            with self._connect_lock:
                internal_disconnect = self._disconnecting
                self.control_connected = False
                self.data_connected = False
                self.file_connected = False
                if not internal_disconnect and not self._connect_callback_done:
                    self.connect_error = "secure session disconnected during setup"
                    report_setup_failure = True
        self.is_active = False
        self.clipboard.stop()
        self.clipboard_sender.stop()
        self.paste_coordinator.reset()
        self._ensure_clipboard_offer_state()
        with self._clipboard_offer_lock:
            self.remote_clipboard_state.reset()
            self.current_clipboard_offer = ClipboardOffer(
                ClipboardKind.UNKNOWN, 0
            )
            self.current_clipboard_origin = None
        self.hotkey_monitor.stop()
        if internal_disconnect:
            return
        if report_setup_failure:
            error = ConnectionError(self.connect_error)
            self.disconnect(preserve_failure=True, error=error)
            self._report_connect(
                False,
                "Connection was interrupted before setup finished. "
                "Check the network and try again.",
            )
        else:
            self.disconnect()

    def set_screen_size(self, w, h):
        self.input_handler.set_screen_size(w, h)

    def connect(self, host, port, callback):
        self.host = host
        self.control_connected = False
        self.data_connected = False
        self.connect_error = None
        self.file_connected = False
        self._connect_callback = callback
        self._connect_callback_done = False
        self._connect_lock = threading.RLock()
        self._connect_deadline = None
        self._ready_started = False
        
        def _check_both_connected():
            self._maybe_finish_connect()

        def _control_callback(success, err):
            if success:
                self.control_connected = True
                self._connect_deadline = threading.Timer(
                    self.lane_timeout, self._on_lane_binding_timeout
                )
                self._connect_deadline.daemon = True
                self._connect_deadline.start()
                session = self.control_network.session_info
                self.data_network = NetworkClient(
                    self.password,
                    role='data',
                    trust_store=self.trust_store,
                    expected_fingerprint=self.control_network.peer_certificate_fingerprint(),
                    lane_token=session['data_token'],
                    session_id=session['session_id'],
                )
                self.data_network.register_callback('clipboard_sync', self.on_remote_copy)
                self.data_network.register_callback('disconnected', self.on_disconnected)
                self.data_network.connect(host, port + 1, _data_callback)
            else:
                self.connect_error = err
                self.disconnect(
                    preserve_failure=True,
                    error=self.control_network.last_error or ConnectionError(err),
                )
                self._report_connect(False, err)

        def _data_callback(success, err):
            if success:
                self.data_connected = True
                _check_both_connected()
            else:
                self.connect_error = err
                self.disconnect(
                    preserve_failure=True,
                    error=self.data_network.last_error or ConnectionError(err),
                )
                self._report_connect(False, err)

        self.control_network.connect(host, port, _control_callback)

    def _report_connect(self, success, error):
        with self._connect_lock:
            if self._connect_callback_done:
                return
            self._connect_callback_done = True
            callback = self._connect_callback
            deadline, self._connect_deadline = self._connect_deadline, None
        if deadline is not None:
            deadline.cancel()
        if callback:
            callback(success, error)

    def _maybe_finish_connect(self):
        with self._connect_lock:
            if (
                self.connect_error or self._connect_callback_done
                or self._ready_started
                or not (
                    self.control_connected and self.data_connected
                    and self.file_connected
                )
                or not self.control_network.connected
                or self.data_network is None
                or not self.data_network.connected
                or self.file_network.sock is None
            ):
                return False
            self._ready_started = True
            try:
                self.control_network.commit_peer_trust()
                if not self._all_lanes_live():
                    raise ConnectionError(
                        "secure session disconnected while becoming ready"
                    )
                self._ensure_clipboard_sender()
                self.clipboard.start()
                self.hotkey_monitor.start()
                if not self._all_lanes_live():
                    self.clipboard.stop()
                    self.hotkey_monitor.stop()
                    raise ConnectionError(
                        "secure session disconnected while starting services"
                    )
                self._report_connect(True, None)
                return True
            except Exception as error:
                message = public_error_message(error, "secure session setup failed")
                self.connect_error = message
                self.clipboard.stop()
                self.hotkey_monitor.stop()
                self.disconnect(preserve_failure=True, error=error)
                self._report_connect(False, message)
                return False

    def _all_lanes_live(self):
        return (
            self.control_connected and self.data_connected
            and self.file_connected and self.control_network.connected
            and self.data_network is not None
            and self.data_network.connected
            and self.file_network.sock is not None
        )

    def _ensure_clipboard_sender(self):
        sender = getattr(self, 'clipboard_sender', None)
        if sender is None or sender.stopped:
            self.clipboard_sender = LatestWinsSender(
                self._send_clipboard_snapshot
            )

    def _on_lane_binding_timeout(self):
        error = TimeoutError("secondary lanes did not bind before the deadline")
        self.connect_error = str(error)
        self.disconnect(preserve_failure=True, error=error)
        self._report_connect(
            False,
            "Connection timed out before setup finished. "
            "Check the network and try again.",
        )

    def disconnect(self, preserve_failure=False, error=None):
        input_handler = getattr(self, 'input_handler', None)
        if input_handler is not None:
            input_handler.release_all_injected_keys()
        if hasattr(self, '_connect_lock'):
            with self._connect_lock:
                if self._disconnecting:
                    return False
                self._disconnecting = True
        elif self._disconnecting:
            return False
        else:
            self._disconnecting = True
        try:
            self.control_network.disconnect(
                preserve_failure=preserve_failure, error=error
            )
            if self.data_network is not None:
                self.data_network.disconnect(
                    preserve_failure=preserve_failure, error=error
                )
            self.file_network.close()
            return True
        finally:
            self._disconnecting = False

    def on_file_lane_offer(self, data):
        def connect_file_lane():
            try:
                self._connect_file_lane(data)
            except Exception as error:
                logger.error(
                    "Secure file lane connection failed (%s)", error_name(error)
                )
                message = public_error_message(error, "secure file connection failed")
                self.connect_error = message
                self.disconnect(preserve_failure=True, error=error)
                self._report_connect(False, message)

        threading.Thread(target=connect_file_lane, daemon=True).start()

    def _connect_file_lane(self, data):
        port = data.get('port')
        session_id = data.get('session_id')
        session = self.control_network.session_info or {}
        token = session.get('file_token')
        if (not isinstance(port, int) or not isinstance(token, str)
                or session_id != session.get('session_id')):
            raise ValueError("file-lane offer is malformed")
        fingerprint = self.control_network.peer_certificate_fingerprint()
        self.file_network.connect(self.host, port, fingerprint, token, session_id=session_id)
        self.file_connected = True
        if self.control_connected and self.data_connected:
            self._maybe_finish_connect()

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
        self._apply_clipboard_interception()
        direction = data.get('direction')
        ratio = data.get('ratio', 0.5)
        
        w = self.input_handler.screen_width
        h = self.input_handler.screen_height
        
        self.input_handler.inject_position(
            *client_entry_position(direction, w, h, ratio)
        )

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
            self._apply_clipboard_interception()
            self.input_handler.release_all_injected_keys()
            self.control_network.send_message({
                'type': 'switch_back',
                'ratio': ratio
            })

    def on_local_copy(self, snapshot):
        return self.clipboard_sender.submit(snapshot)

    def _send_clipboard_snapshot(self, snapshot):
        payload = encode_clipboard_snapshot(snapshot)
        payload['type'] = 'clipboard_sync'
        revision = snapshot.get('_deskflow_offer_revision')
        if isinstance(revision, int) and not isinstance(revision, bool):
            payload['offer_revision'] = revision
        return self.data_network is not None and self.data_network.send_message(payload)

    def on_remote_copy(self, data):
        if 'offer_revision' not in data:
            self.clipboard.inject(data)
            return
        self._ensure_clipboard_offer_state()
        with self._clipboard_offer_lock:
            payload = self.remote_clipboard_state.receive_payload(data)
            if payload is not None and self._remote_payload_is_current(payload):
                self.clipboard.inject(payload)

    def _ensure_clipboard_offer_state(self):
        if not hasattr(self, '_clipboard_offer_lock'):
            self._clipboard_offer_lock = threading.RLock()
        if not hasattr(self, 'remote_clipboard_state'):
            self.remote_clipboard_state = RemoteClipboardState()
        if not hasattr(self, 'local_clipboard_offer'):
            self.local_clipboard_offer = ClipboardOffer(
                ClipboardKind.UNKNOWN, 0
            )
        if not hasattr(self, 'current_clipboard_offer'):
            self.current_clipboard_offer = ClipboardOffer(
                ClipboardKind.UNKNOWN, 0
            )
        if not hasattr(self, 'current_clipboard_origin'):
            self.current_clipboard_origin = None

    def on_local_clipboard_offer(self, offer):
        if not isinstance(offer, ClipboardOffer) or offer.kind is ClipboardKind.UNKNOWN:
            return False
        self._ensure_clipboard_offer_state()
        with self._clipboard_offer_lock:
            if offer.revision <= self.local_clipboard_offer.revision:
                logger.info(
                    "Client ignored stale local clipboard offer: revision=%d",
                    offer.revision,
                )
                return False
            self.local_clipboard_offer = offer
            self.current_clipboard_offer = offer
            self.current_clipboard_origin = 'local'
            self._apply_clipboard_interception()
        logger.info(
            "Client sending clipboard offer: kind=%s revision=%d",
            offer.kind.value,
            offer.revision,
        )
        return self.control_network.send_message({
            'type': 'clipboard_offer',
            'kind': offer.kind.value,
            'revision': offer.revision,
        })

    def on_remote_clipboard_offer(self, data):
        self._ensure_clipboard_offer_state()
        with self._clipboard_offer_lock:
            applied = self.remote_clipboard_state.receive_offer(data)
            if applied is None:
                logger.warning("Client ignored stale or malformed clipboard offer")
                return False
            offer, payload = applied
            self.current_clipboard_offer = offer
            self.current_clipboard_origin = 'remote'
            self._apply_clipboard_interception()
            logger.info(
                "Client received clipboard offer: kind=%s revision=%d",
                offer.kind.value,
                offer.revision,
            )
            if payload is not None and self._remote_payload_is_current(payload):
                self.clipboard.inject(payload)
        return True

    def _remote_payload_is_current(self, payload):
        return (
            self.current_clipboard_origin == 'remote'
            and self.current_clipboard_offer.kind is ClipboardKind.ORDINARY
            and payload.get('offer_revision')
            == self.current_clipboard_offer.revision
        )

    def _apply_clipboard_interception(self):
        self._ensure_clipboard_offer_state()
        enabled = (
            getattr(self, 'is_active', False)
            and self.current_clipboard_origin == 'remote'
            and self.current_clipboard_offer.kind is ClipboardKind.FILES
        )
        coordinator = getattr(self, 'paste_coordinator', None)
        if coordinator is not None:
            coordinator.set_remote_files_available(enabled)

    def _refresh_clipboard_before_paste(self):
        return self.clipboard.refresh_current_offer() is not None

    def on_local_file_availability(self, available):
        local_files_available = available is True
        logger.info(
            "Client sending local file offer: available=%s",
            str(local_files_available).lower(),
        )
        return self.control_network.send_message({
            'type': 'file_clipboard_available',
            'available': local_files_available,
        })

    def on_remote_file_availability(self, data):
        remote_files_available = data.get('available') is True
        logger.info(
            "Client received remote file offer: available=%s",
            str(remote_files_available).lower(),
        )
        self.paste_coordinator.set_remote_files_available(remote_files_available)

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
