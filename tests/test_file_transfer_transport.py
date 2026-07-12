import struct
import unittest
import hashlib
import ssl
import threading

from app.crypto import CERT_FILE, KEY_FILE, ensure_certificates
from pathlib import Path
import tempfile
from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.sender import TransferSender
from app.file_transfer.source import SourceFile

from app.file_transfer.protocol import FrameError, encode_frame
from app.file_transfer.protocol import AuthenticationError, SessionAuthenticator
from app.file_transfer.transport import (
    FileLaneClient,
    FileLaneServer,
    authenticate_client_connection,
    authenticate_server_connection,
    read_frame,
    send_frame,
)


class FragmentedSocket:
    def __init__(self, incoming=b"", fragment_size=3):
        self.incoming = bytearray(incoming)
        self.fragment_size = fragment_size
        self.sent = bytearray()

    def recv(self, size):
        if not self.incoming:
            return b""
        count = min(size, self.fragment_size, len(self.incoming))
        data = bytes(self.incoming[:count])
        del self.incoming[:count]
        return data

    def sendall(self, data):
        self.sent.extend(data)

    def getpeercert(self, binary_form=False):
        return b"file peer certificate" if binary_form else {}


class TransportTests(unittest.TestCase):
    def test_reads_fragmented_frame_without_unbounded_allocation(self):
        sock = FragmentedSocket(encode_frame({"type": "status"}, b"ok"))

        metadata, payload = read_frame(sock)

        self.assertEqual(metadata, {"type": "status"})
        self.assertEqual(payload, b"ok")

    def test_rejects_oversized_header_before_reading_body(self):
        sock = FragmentedSocket(struct.pack(">II", 65_537, 0))
        with self.assertRaises(FrameError):
            read_frame(sock)

    def test_send_frame_uses_the_bounded_protocol(self):
        sock = FragmentedSocket()
        send_frame(sock, {"type": "status"}, b"ok")
        self.assertEqual(read_frame(FragmentedSocket(sock.sent)), ({"type": "status"}, b"ok"))

    def test_server_accepts_one_use_token_and_rejects_replay(self):
        authenticator = SessionAuthenticator("one-use-token")
        first = FragmentedSocket(encode_frame({"type": "authenticate", "token": "one-use-token"}))
        authenticate_server_connection(first, authenticator)
        self.assertEqual(read_frame(FragmentedSocket(first.sent))[0]["type"], "authenticated")

        replay = FragmentedSocket(encode_frame({"type": "authenticate", "token": "one-use-token"}))
        with self.assertRaises(AuthenticationError):
            authenticate_server_connection(replay, authenticator)

    def test_client_requires_file_lane_to_match_control_certificate(self):
        reply = encode_frame({"type": "authenticated"})
        expected = hashlib.sha256(b"file peer certificate").hexdigest()
        sock = FragmentedSocket(reply)
        authenticate_client_connection(sock, expected, "one-use-token")

        wrong = FragmentedSocket(reply)
        with self.assertRaises(AuthenticationError):
            authenticate_client_connection(wrong, "0" * 64, "one-use-token")

    def test_tls_file_lane_authenticates_and_delivers_bounded_event(self):
        ensure_certificates()
        received = []
        delivered = threading.Event()
        server = FileLaneServer(CERT_FILE, KEY_FILE, host="127.0.0.1", port=0)
        server.register_callback(
            "status",
            lambda metadata, payload: (received.append((metadata, payload)), delivered.set()),
        )
        token = server.issue_session()
        self.assertTrue(server.start())
        client = FileLaneClient()
        with open(CERT_FILE, encoding="ascii") as certificate_file:
            certificate_der = ssl.PEM_cert_to_DER_cert(certificate_file.read())
        fingerprint = hashlib.sha256(certificate_der).hexdigest()
        try:
            client.connect("127.0.0.1", server.port, fingerprint, token)
            client.send({"type": "status", "job_id": "safe"}, b"ok")
            self.assertTrue(delivered.wait(2))
            self.assertEqual(received, [({"type": "status", "job_id": "safe"}, b"ok")])
        finally:
            client.close()
            server.stop()

    def test_tls_lane_transfers_file_with_end_to_end_hash_verification(self):
        ensure_certificates()
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as receive_directory:
            source_path = Path(source_directory) / "source.txt"
            source_path.write_bytes(b"verified over TLS")
            source = SourceFile.snapshot(source_path)
            manifest = Manifest.create([
                FileItem("received.txt", ItemType.FILE, source.size, source.modified_ns, source.sha256)
            ])
            server = FileLaneServer(CERT_FILE, KEY_FILE, host="127.0.0.1", port=0)
            TransferReceiver(Path(receive_directory)).attach(server)
            token = server.issue_session()
            self.assertTrue(server.start())
            client = FileLaneClient()
            with open(CERT_FILE, encoding="ascii") as certificate_file:
                fingerprint = hashlib.sha256(
                    ssl.PEM_cert_to_DER_cert(certificate_file.read())
                ).hexdigest()
            try:
                client.connect("127.0.0.1", server.port, fingerprint, token)
                TransferSender(client).send_job(manifest, {"received.txt": source})
                completed = Path(receive_directory) / "completed" / "received.txt"
                for _ in range(100):
                    if completed.exists():
                        break
                    threading.Event().wait(0.01)
                self.assertEqual(completed.read_bytes(), b"verified over TLS")
            finally:
                client.close()
                server.stop()


if __name__ == "__main__":
    unittest.main()
