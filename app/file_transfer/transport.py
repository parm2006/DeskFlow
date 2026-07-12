import struct
import secrets
import socket
import ssl
import threading

from .protocol import (
    MAX_METADATA_SIZE,
    MAX_PAYLOAD_SIZE,
    FrameError,
    decode_frame,
    encode_frame,
    verify_certificate_fingerprint,
    SessionAuthenticator,
)


_HEADER = struct.Struct(">II")


def _receive_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise FrameError("connection closed during a frame")
        data.extend(chunk)
    return bytes(data)


def read_frame(sock):
    header = _receive_exact(sock, _HEADER.size)
    metadata_size, payload_size = _HEADER.unpack(header)
    if metadata_size > MAX_METADATA_SIZE or payload_size > MAX_PAYLOAD_SIZE:
        raise FrameError("frame declares an oversized section")
    body = _receive_exact(sock, metadata_size + payload_size)
    return decode_frame(header + body)


def send_frame(sock, metadata, payload=b""):
    sock.sendall(encode_frame(metadata, payload))


def authenticate_server_connection(sock, authenticator):
    metadata, payload = read_frame(sock)
    if payload or metadata.get("type") != "authenticate":
        raise FrameError("file lane must authenticate before sending data")
    authenticator.authenticate(metadata.get("token"))
    send_frame(sock, {"type": "authenticated"})


def authenticate_client_connection(sock, expected_fingerprint, token):
    certificate = sock.getpeercert(binary_form=True)
    verify_certificate_fingerprint(certificate, expected_fingerprint)
    send_frame(sock, {"type": "authenticate", "token": token})
    metadata, payload = read_frame(sock)
    if payload or metadata.get("type") != "authenticated":
        raise FrameError("file lane authentication was not acknowledged")


class _FileLane:
    def __init__(self):
        self.sock = None
        self._callbacks = {}
        self._send_lock = threading.Lock()

    def register_callback(self, event_type, callback):
        self._callbacks.setdefault(event_type, []).append(callback)

    def send(self, metadata, payload=b""):
        if self.sock is None:
            raise ConnectionError("file lane is not connected")
        with self._send_lock:
            send_frame(self.sock, metadata, payload)

    def _receive_loop(self):
        try:
            while self.sock is not None:
                metadata, payload = read_frame(self.sock)
                for callback in self._callbacks.get(metadata.get("type"), ()):
                    callback(metadata, payload)
        except (ConnectionError, OSError, FrameError):
            pass
        finally:
            self.close()

    def close(self):
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
            for callback in self._callbacks.get("disconnected", ()):
                callback({"type": "disconnected"}, b"")


class FileLaneClient(_FileLane):
    def connect(self, host, port, expected_fingerprint, token, timeout=3):
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            secure_sock = context.wrap_socket(raw_sock, server_hostname=host)
            authenticate_client_connection(secure_sock, expected_fingerprint, token)
        except Exception:
            raw_sock.close()
            raise
        secure_sock.settimeout(None)
        self.sock = secure_sock
        threading.Thread(target=self._receive_loop, daemon=True).start()


class FileLaneServer(_FileLane):
    def __init__(self, cert_file, key_file, host="0.0.0.0", port=5002):
        super().__init__()
        self.host = host
        self.port = port
        self._server_sock = None
        self._running = False
        self._authenticator = None
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.load_cert_chain(certfile=cert_file, keyfile=key_file)

    def issue_session(self):
        token = secrets.token_urlsafe(32)
        self._authenticator = SessionAuthenticator(token)
        return token

    def start(self):
        try:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((self.host, self.port))
            server_sock.listen(1)
            server_sock.settimeout(0.2)
            self.port = server_sock.getsockname()[1]
            self._server_sock = server_sock
            self._running = True
            threading.Thread(target=self._accept_loop, daemon=True).start()
            return True
        except OSError:
            self.stop()
            return False

    def _accept_loop(self):
        while self._running:
            try:
                raw_sock, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                secure_sock = self._context.wrap_socket(raw_sock, server_side=True)
                if self._authenticator is None:
                    raise AuthenticationError("no file-lane session was offered")
                authenticate_server_connection(secure_sock, self._authenticator)
                self.sock = secure_sock
                self._authenticator = None
                self._receive_loop()
            except Exception:
                raw_sock.close()

    def stop(self):
        self._running = False
        self.close()
        server_sock, self._server_sock = self._server_sock, None
        if server_sock is not None:
            server_sock.close()
