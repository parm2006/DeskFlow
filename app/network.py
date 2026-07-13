import socket
import threading
import json
import struct
import logging
import ssl
import time
import hashlib
import os
from app.crypto import ensure_certificates, CERT_FILE, KEY_FILE, materialize_private_key
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NetworkNode:
    def __init__(self):
        self.sock = None
        self.connected = False
        self.authenticated = False
        self.callbacks = {} # event_type -> list of callback functions
        self.receive_thread = None
        self._send_lock = threading.Lock()

    def register_callback(self, event_type, callback):
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(callback)

    def peer_certificate_fingerprint(self):
        if self.sock is None or not hasattr(self.sock, "getpeercert"):
            raise RuntimeError("there is no live TLS peer certificate")
        certificate = self.sock.getpeercert(binary_form=True)
        if not certificate:
            raise RuntimeError("there is no live TLS peer certificate")
        return hashlib.sha256(certificate).hexdigest()

    def trigger_callbacks(self, event_type, data):
        for cb in self.callbacks.get(event_type, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def send_message(self, msg_dict):
        if not self.connected or not self.sock:
            return False
        try:
            payload = json.dumps(msg_dict).encode('utf-8')
            # 4-byte length prefix (big-endian)
            header = struct.pack('>I', len(payload))
            with self._send_lock:
                if not self.connected or not self.sock:
                    return False
                self.sock.sendall(header + payload)
            return True
        except Exception as e:
            logger.error(f"Send error: {e}")
            self.disconnect()
            return False

    def _receive_loop(self, conn):
        try:
            while self.connected:
                # Read 4-byte header
                raw_msglen = self._recvall(conn, 4)
                if not raw_msglen:
                    break
                msglen = struct.unpack('>I', raw_msglen)[0]
                
                # Read payload
                data = self._recvall(conn, msglen)
                if not data:
                    break
                
                msg_dict = json.loads(data.decode('utf-8'))
                if not isinstance(msg_dict, dict):
                    logger.error("Received payload is not a JSON object/dictionary")
                    break
                event_type = msg_dict.get('type')
                
                if not self.authenticated:
                    if getattr(self, 'is_server', False):
                        if event_type == 'auth' and msg_dict.get('password') == self.password:
                            self.authenticated = True
                            self.send_message({'type': 'auth_success'})
                            self.trigger_callbacks('connected', {'addr': getattr(self, 'client_addr', None)})
                            continue
                        else:
                            logger.error("Authentication failed")
                            break
                    else:
                        if event_type == 'auth_success':
                            self.authenticated = True
                            self.trigger_callbacks('connected', {'host': getattr(self, 'host', None)})
                            continue
                        
                if not self.authenticated:
                    continue
                    
                if event_type:
                    self.trigger_callbacks(event_type, msg_dict)
                else:
                    logger.warning("Received message without type")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
        finally:
            self.disconnect()

    def _recvall(self, conn, n):
        data = bytearray()
        while len(data) < n:
            packet = conn.recv(n - len(data))
            if not packet:
                return None
            data.extend(packet)
        return data

    def disconnect(self):
        was_connected = self.connected
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        if was_connected:
            self.trigger_callbacks('disconnected', {})

class NetworkServer(NetworkNode):
    def __init__(self, password, host='0.0.0.0', port=5000):
        super().__init__()
        self.is_server = True
        self.password = password
        self.host = host
        self.port = port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.accept_thread = None
        
        ensure_certificates()
        self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        temporary_key = materialize_private_key()
        try:
            self.ssl_context.load_cert_chain(certfile=CERT_FILE, keyfile=temporary_key)
        finally:
            try: os.unlink(temporary_key)
            except OSError: pass

    def start(self):
        try:
            self.server_sock.bind((self.host, self.port))
            self.server_sock.listen(1)
            logger.info(f"Server listening on {self.host}:{self.port}")
            self.accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            self.accept_thread.start()
            return True
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return False

    def _accept_loop(self):
        try:
            while True:
                conn, addr = self.server_sock.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                logger.info(f"Client attempting connection from {addr}")
                
                # Wrap with SSL
                try:
                    secure_conn = self.ssl_context.wrap_socket(conn, server_side=True)
                except Exception as e:
                    logger.error(f"SSL Handshake failed: {e}")
                    conn.close()
                    continue

                if self.connected:
                    logger.info("Already connected, dropping new connection")
                    secure_conn.close()
                    continue
                
                self.sock = secure_conn
                self.client_addr = addr
                self.connected = True
                self.authenticated = False
                
                self.receive_thread = threading.Thread(target=self._receive_loop, args=(secure_conn,), daemon=True)
                self.receive_thread.start()
        except Exception as e:
            logger.error(f"Accept loop error: {e}")

    def stop(self):
        self.disconnect()
        try:
            self.server_sock.close()
        except:
            pass

class NetworkClient(NetworkNode):
    def __init__(self, password, expected_fingerprint=None, fingerprint_approval=None):
        super().__init__()
        self.is_server = False
        self.password = password
        self.expected_fingerprint = expected_fingerprint
        self.fingerprint_approval = fingerprint_approval

    def _pin_path(self, host):
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeskFlow" / "peers" / (host.replace("/", "_") + ".fingerprint")

    def connect(self, host, port, callback):
        def _connect_thread():
            try:
                self.host = host
                raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                raw_sock.settimeout(3.0) # 3 second timeout for IP unreachable
                raw_sock.connect((host, port))
                raw_sock.settimeout(None) # Restore blocking mode for SSL
                
                ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                
                self.sock = ssl_context.wrap_socket(raw_sock, server_hostname=host)
                fingerprint = self.peer_certificate_fingerprint()
                expected = self.expected_fingerprint
                pin_path = self._pin_path(host)
                if expected is None and pin_path.exists():
                    expected = pin_path.read_text(encoding="ascii").strip()
                if expected is not None and fingerprint != expected:
                    raise ssl.SSLError(
                        "peer certificate changed; remove the saved DeskFlow peer fingerprint and pair again"
                    )
                if expected is None:
                    if self.fingerprint_approval is not None and not self.fingerprint_approval(fingerprint, host):
                        raise ssl.SSLError("peer certificate fingerprint was not approved")
                    pin_path.parent.mkdir(parents=True, exist_ok=True)
                    pin_path.write_text(fingerprint, encoding="ascii")
                self.connected = True
                self.authenticated = False
                
                self.receive_thread = threading.Thread(target=self._receive_loop, args=(self.sock,), daemon=True)
                self.receive_thread.start()
                
                # Send auth packet
                self.send_message({'type': 'auth', 'password': self.password})
                
                # Wait for auth response (timeout after 2s)
                start_time = time.time()
                while not self.authenticated and self.connected:
                    if time.time() - start_time > 2.0:
                        logger.error("Authentication timed out")
                        self.disconnect()
                        if callback: callback(False, "Authentication timed out")
                        return
                    time.sleep(0.1)
                    
                if self.authenticated:
                    if callback: callback(True, None)
                else:
                    if callback: callback(False, "Connection disconnected during auth")
            except Exception as e:
                logger.error(f"Failed to connect to {host}:{port}: {e}")
                if callback: callback(False, str(e))
                
        threading.Thread(target=_connect_thread, daemon=True).start()
