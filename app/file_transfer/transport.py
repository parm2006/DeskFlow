import struct
import secrets
import socket
import ssl
import threading
import logging

from app.crypto import load_identity

from .protocol import (
    MAX_METADATA_SIZE,
    MAX_PAYLOAD_SIZE,
    AuthenticationError,
    FrameError,
    decode_frame,
    encode_frame,
    verify_certificate_fingerprint,
    SessionAuthenticator,
)


_HEADER = struct.Struct(">II")
logger = logging.getLogger(__name__)


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


def authenticate_server_connection(sock, authenticator, expected_session_id=None):
    metadata, payload = read_frame(sock)
    if payload or metadata.get("type") != "authenticate":
        raise FrameError("file lane must authenticate before sending data")
    if expected_session_id is not None and metadata.get("session_id") != expected_session_id:
        raise AuthenticationError("file lane belongs to another session")
    if hasattr(authenticator, "consume_lane"):
        authenticator.consume_lane(
            metadata.get("token"), "file", metadata.get("session_id")
        )
    else:
        authenticator.authenticate(metadata.get("token"))
    send_frame(sock, {"type": "authenticated", "session_id": expected_session_id})


def authenticate_client_connection(sock, expected_fingerprint, token, session_id=None):
    certificate = sock.getpeercert(binary_form=True)
    verify_certificate_fingerprint(certificate, expected_fingerprint)
    send_frame(sock, {"type": "authenticate", "token": token, "session_id": session_id})
    metadata, payload = read_frame(sock)
    if (
        payload or metadata.get("type") != "authenticated"
        or metadata.get("session_id") != session_id
    ):
        raise FrameError("file lane authentication was not acknowledged")


class _FileLane:
    def __init__(self):
        self.sock = None
        self._callbacks = {}
        self._send_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._generation = 0

    def register_callback(self, event_type, callback):
        self._callbacks.setdefault(event_type, []).append(callback)

    def send(self, metadata, payload=b""):
        with self._state_lock:
            sock = self.sock
            generation = self._generation
        if sock is None:
            raise ConnectionError("file lane is not connected")
        with self._send_lock:
            with self._state_lock:
                if self.sock is not sock or self._generation != generation:
                    raise ConnectionError("file lane was replaced")
            send_frame(sock, metadata, payload)

    def _attach(self, sock):
        with self._state_lock:
            previous = self.sock
            self._generation += 1
            generation = self._generation
            self.sock = sock
        if previous is not None and previous is not sock:
            self._close(previous)
        return generation

    def _receive_loop(self, sock, generation):
        try:
            while True:
                with self._state_lock:
                    if self.sock is not sock or self._generation != generation:
                        return
                metadata, payload = read_frame(sock)
                for callback in self._callbacks.get(metadata.get("type"), ()):
                    try:
                        callback(metadata, payload)
                    except Exception:
                        logger.exception(
                            "File-lane callback failed for event %s; connection remains available",
                            metadata.get("type"),
                        )
        except (ConnectionError, OSError, FrameError):
            pass
        finally:
            self._close_generation(sock, generation)

    def _close_generation(self, sock, generation):
        with self._state_lock:
            if self.sock is not sock or self._generation != generation:
                self._close(sock)
                return False
            self.sock = None
        self._close(sock)
        for callback in self._callbacks.get("disconnected", ()):
            callback({"type": "disconnected"}, b"")
        return True

    def close(self):
        with self._state_lock:
            sock = self.sock
            generation = self._generation
        if sock is not None:
            return self._close_generation(sock, generation)
        return False

    @staticmethod
    def _close(sock):
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass


class FileLaneClient(_FileLane):
    def connect(self, host, port, expected_fingerprint, token, session_id=None, timeout=3):
        raw_sock = socket.create_connection((host, port), timeout=timeout)
        secure_sock = None
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        try:
            raw_sock.settimeout(timeout)
            secure_sock = context.wrap_socket(raw_sock, server_hostname=host)
            authenticate_client_connection(
                secure_sock, expected_fingerprint, token, session_id=session_id
            )
        except Exception:
            self._close(secure_sock if secure_sock is not None else raw_sock)
            raise
        secure_sock.settimeout(None)
        generation = self._attach(secure_sock)
        for callback in self._callbacks.get("connected", ()):
            callback({"type": "connected", "session_id": session_id}, b"")
        threading.Thread(
            target=self._receive_loop, args=(secure_sock, generation), daemon=True
        ).start()


class FileLaneServer(_FileLane):
    def __init__(
        self,
        cert_file=None,
        key_file=None,
        host="0.0.0.0",
        port=5002,
        *,
        key_password=None,
        identity=None,
        handshake_timeout=3.0,
        auth_timeout=10.0,
        coordinator=None,
    ):
        super().__init__()
        self.host = host
        self.port = port
        self._server_sock = None
        self._running = False
        self._server_generation = 0
        self._candidate_slots = threading.BoundedSemaphore(8)
        self._candidate_lock = threading.Lock()
        self._candidate_sockets = set()
        self._authenticator = None
        self._expected_session_id = None
        self.coordinator = coordinator
        self._auth_lock = threading.Lock()
        self.handshake_timeout = float(handshake_timeout)
        self.auth_timeout = float(auth_timeout)
        if identity is None and (cert_file is None or key_file is None):
            identity = load_identity()
        if identity is not None:
            cert_file = identity.cert_path
            key_file = identity.key_path
            key_password = identity.password
        self._context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._context.load_cert_chain(
            certfile=cert_file,
            keyfile=key_file,
            password=key_password,
        )

    def issue_session(self):
        token = secrets.token_urlsafe(32)
        self.offer_session(token)
        return token

    def offer_session(self, token, session_id=None):
        with self._auth_lock:
            self._authenticator = (
                self.coordinator if self.coordinator is not None
                else SessionAuthenticator(token)
            )
            self._expected_session_id = session_id

    def revoke_session(self):
        with self._auth_lock:
            self._authenticator = None
            self._expected_session_id = None

    def close(self):
        self.revoke_session()
        return super().close()

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
            self._server_generation += 1
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
            if not self._candidate_slots.acquire(blocking=False):
                self._close(raw_sock)
                continue
            with self._candidate_lock:
                self._candidate_sockets.add(raw_sock)
            threading.Thread(
                target=self._candidate_worker,
                args=(raw_sock, self._server_generation),
                daemon=True,
            ).start()

    def _candidate_worker(self, raw_sock, server_generation):
        try:
            self._handle_candidate(raw_sock, server_generation)
        finally:
            with self._candidate_lock:
                self._candidate_sockets.discard(raw_sock)
            self._candidate_slots.release()

    def _handle_candidate(self, raw_sock, server_generation=None):
        secure_sock = None
        try:
            raw_sock.settimeout(self.handshake_timeout)
            secure_sock = self._context.wrap_socket(raw_sock, server_side=True)
            with self._candidate_lock:
                self._candidate_sockets.discard(raw_sock)
                self._candidate_sockets.add(secure_sock)
            secure_sock.settimeout(self.auth_timeout)
            with self._auth_lock:
                if (
                    not self._running
                    or server_generation != self._server_generation
                ):
                    raise AuthenticationError("file server stopped during authentication")
                if self._authenticator is None:
                    raise AuthenticationError("no file-lane session was offered")
                authenticator = self._authenticator
                expected_session_id = self._expected_session_id
            authenticate_server_connection(
                secure_sock,
                authenticator,
                expected_session_id=expected_session_id,
            )
            with self._auth_lock:
                if (
                    not self._running
                    or server_generation != self._server_generation
                    or self._authenticator is not authenticator
                    or self._expected_session_id != expected_session_id
                ):
                    raise AuthenticationError("file session changed during authentication")
                self._authenticator = None
                session_id, self._expected_session_id = self._expected_session_id, None
                secure_sock.settimeout(None)
                generation = self._attach(secure_sock)
            with self._candidate_lock:
                self._candidate_sockets.discard(secure_sock)
            for callback in self._callbacks.get("connected", ()):
                callback({"type": "connected", "session_id": session_id}, b"")
            self._receive_loop(secure_sock, generation)
        except Exception:
            if secure_sock is not None:
                self._close(secure_sock)
            else:
                self._close(raw_sock)
        finally:
            with self._candidate_lock:
                self._candidate_sockets.discard(raw_sock)
                if secure_sock is not None:
                    self._candidate_sockets.discard(secure_sock)

    def stop(self):
        with self._auth_lock:
            self._running = False
            self._server_generation += 1
            self._authenticator = None
            self._expected_session_id = None
        with self._candidate_lock:
            candidates = tuple(self._candidate_sockets)
            self._candidate_sockets.clear()
        for candidate in candidates:
            self._close(candidate)
        self.close()
        server_sock, self._server_sock = self._server_sock, None
        if server_sock is not None:
            server_sock.close()
