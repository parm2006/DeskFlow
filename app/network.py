import socket
import threading
import json
import struct
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NetworkNode:
    def __init__(self):
        self.sock = None
        self.connected = False
        self.callbacks = {} # event_type -> list of callback functions
        self.receive_thread = None

    def register_callback(self, event_type, callback):
        if event_type not in self.callbacks:
            self.callbacks[event_type] = []
        self.callbacks[event_type].append(callback)

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
                event_type = msg_dict.get('type')
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
    def __init__(self, host='0.0.0.0', port=5000):
        super().__init__()
        self.host = host
        self.port = port
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.accept_thread = None

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
                logger.info(f"Client connected from {addr}")
                # For phase 1, only handle one client at a time
                if self.connected:
                    logger.info("Already connected, dropping new connection")
                    conn.close()
                    continue
                
                self.sock = conn
                self.connected = True
                self.trigger_callbacks('connected', {'addr': addr})
                
                self.receive_thread = threading.Thread(target=self._receive_loop, args=(conn,), daemon=True)
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
    def connect(self, host, port=5000):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, port))
            self.connected = True
            self.trigger_callbacks('connected', {'host': host, 'port': port})
            
            self.receive_thread = threading.Thread(target=self._receive_loop, args=(self.sock,), daemon=True)
            self.receive_thread.start()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {host}:{port}: {e}")
            return False
