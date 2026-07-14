import socket
import ssl
import tempfile
import threading
import time
import unittest

from app.crypto import IdentityStore
from app.network import (
    ConnectionPhase, NetworkClient, NetworkNode, NetworkServer,
    PairingTimeout, PeerIdentityChanged,
)
from app.session import SessionAuthenticationError, SessionCoordinator
from app.trust import PeerTrustStore


class FakeProtector:
    def protect(self, value):
        return b"p:" + bytes(value)[::-1]

    def unprotect(self, value):
        if not bytes(value).startswith(b"p:"):
            raise ValueError("invalid protected value")
        return bytes(value)[2:][::-1]


class FakeSocket:
    def __init__(self):
        self.closed = False

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True


class NetworkGenerationTests(unittest.TestCase):
    def test_stale_receive_loop_cannot_disconnect_replacement_socket(self):
        node = NetworkNode()
        first = FakeSocket()
        second = FakeSocket()
        first_generation = node._attach_socket(first)
        node._attach_socket(second)

        self.assertFalse(node._disconnect_socket(first, first_generation))

        self.assertTrue(node.connected)
        self.assertIs(node.sock, second)
        self.assertFalse(second.closed)

    def test_pairing_approval_has_a_deadline(self):
        blocker = threading.Event()
        client = NetworkClient(
            "secret",
            fingerprint_approval=lambda fingerprint, peer: blocker.wait(1),
            approval_timeout=0.01,
        )
        with self.assertRaises(PairingTimeout):
            client._request_pairing_approval("a" * 64, object())

    def test_pairing_ui_timeout_is_preserved_as_a_typed_failure(self):
        def timed_out(fingerprint, peer):
            raise PairingTimeout("pairing decision timed out")

        client = NetworkClient(
            "secret", fingerprint_approval=timed_out,
            approval_timeout=1,
        )
        with self.assertRaisesRegex(PairingTimeout, "decision timed out"):
            client._request_pairing_approval("a" * 64, object())


class SecureControlConnectionTests(unittest.TestCase):
    def setUp(self):
        self.identity_directory = tempfile.TemporaryDirectory()
        self.trust_directory = tempfile.TemporaryDirectory()
        self.identity = IdentityStore(
            self.identity_directory.name,
            legacy_root=False,
            protector=FakeProtector(),
        ).load_or_create()
        self.coordinator = SessionCoordinator("secret")
        self.server = NetworkServer(
            "secret",
            "127.0.0.1",
            0,
            role="control",
            coordinator=self.coordinator,
            identity=self.identity,
            handshake_timeout=0.3,
            auth_timeout=0.5,
        )
        self.assertTrue(self.server.start())
        self.trust = PeerTrustStore(self.trust_directory.name, protector=FakeProtector())

    def tearDown(self):
        self.server.stop()
        self.identity_directory.cleanup()
        self.trust_directory.cleanup()

    def connect(self, password="secret", approval=lambda fingerprint, peer: True):
        event = threading.Event()
        result = []
        client = NetworkClient(
            password,
            trust_store=self.trust,
            fingerprint_approval=approval,
            handshake_timeout=1.0,
            auth_timeout=1.0,
        )
        client.connect(
            "127.0.0.1",
            self.server.port,
            lambda success, error: (result.append((success, error)), event.set()),
        )
        self.assertTrue(event.wait(3), "connection callback did not run")
        return client, result[0]

    def test_pin_is_committed_only_after_full_lane_binding(self):
        client, result = self.connect()
        peer = self.trust.peer_id("127.0.0.1", self.server.port)
        try:
            self.assertEqual(result, (True, None))
            self.assertEqual(client.phase, ConnectionPhase.BINDING_LANES)
            self.assertIsNone(self.trust.load(peer))
            self.assertTrue(client.commit_peer_trust())
            self.assertEqual(client.phase, ConnectionPhase.CONNECTED)
            self.assertEqual(self.trust.load(peer), client.peer_certificate_fingerprint())
        finally:
            client.disconnect()

    def test_disconnect_before_lane_binding_discards_pending_trust(self):
        client, result = self.connect()
        peer = self.trust.peer_id("127.0.0.1", self.server.port)
        self.assertEqual(result, (True, None))
        client.disconnect()

        self.assertFalse(client.commit_peer_trust())
        self.assertEqual(client.phase, ConnectionPhase.DISCONNECTED)
        self.assertIsNone(self.trust.load(peer))

    def test_concurrent_disconnect_cannot_resurrect_connected_phase(self):
        client, result = self.connect()
        self.assertEqual(result, (True, None))
        entered_commit = threading.Event()
        release_commit = threading.Event()
        original_commit = self.trust.commit

        def blocking_commit(peer, fingerprint):
            entered_commit.set()
            release_commit.wait(1)
            original_commit(peer, fingerprint)

        self.trust.commit = blocking_commit
        commit_result = []
        commit_thread = threading.Thread(
            target=lambda: commit_result.append(client.commit_peer_trust())
        )
        disconnect_thread = threading.Thread(target=client.disconnect)
        commit_thread.start()
        self.assertTrue(entered_commit.wait(1))
        disconnect_thread.start()
        release_commit.set()
        commit_thread.join(1)
        disconnect_thread.join(1)

        self.assertEqual(commit_result, [True])
        self.assertFalse(client.connected)
        self.assertEqual(client.phase, ConnectionPhase.DISCONNECTED)

    def test_wrong_password_leaves_no_pin_and_server_accepts_a_later_client(self):
        bad, result = self.connect(password="wrong")
        peer = self.trust.peer_id("127.0.0.1", self.server.port)
        bad.disconnect()
        self.assertFalse(result[0])
        self.assertEqual(bad.phase, ConnectionPhase.DISCONNECTED)
        self.assertIsInstance(bad.last_error, SessionAuthenticationError)
        self.assertIsNone(self.trust.load(peer))

    def test_declined_pairing_retains_typed_failure_without_a_pin(self):
        client, result = self.connect(approval=lambda fingerprint, peer: False)
        peer = self.trust.peer_id("127.0.0.1", self.server.port)
        self.assertFalse(result[0])
        self.assertEqual(client.phase, ConnectionPhase.FAILED)
        self.assertIsNotNone(client.last_error)
        self.assertIsNone(self.trust.load(peer))

        deadline = time.monotonic() + 2
        while self.server.connected and time.monotonic() < deadline:
            time.sleep(0.01)
        good, good_result = self.connect()
        try:
            self.assertEqual(good_result, (True, None))
        finally:
            good.disconnect()

    def test_stalled_tls_handshake_does_not_block_a_valid_client(self):
        stalled = socket.create_connection(("127.0.0.1", self.server.port), timeout=1)
        try:
            client, result = self.connect()
            try:
                self.assertEqual(result, (True, None))
            finally:
                client.disconnect()
        finally:
            stalled.close()

    def test_stalled_password_auth_does_not_block_a_valid_client(self):
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection(("127.0.0.1", self.server.port), timeout=1)
        stalled = context.wrap_socket(raw, server_hostname="127.0.0.1")
        try:
            client, result = self.connect()
            try:
                self.assertEqual(result, (True, None))
            finally:
                client.disconnect()
        finally:
            stalled.close()

    def test_changed_identity_requires_explicit_repair(self):
        peer = self.trust.peer_id("127.0.0.1", self.server.port)
        old_fingerprint = "0" * 64
        self.trust.commit(peer, old_fingerprint)
        client, result = self.connect()
        self.assertFalse(result[0])
        self.assertIsInstance(client.last_error, PeerIdentityChanged)
        self.assertEqual(self.trust.load(peer), old_fingerprint)

        self.assertTrue(self.trust.clear(peer))
        repaired, repaired_result = self.connect()
        try:
            self.assertEqual(repaired_result, (True, None))
            self.assertTrue(repaired.commit_peer_trust())
            self.assertEqual(
                self.trust.load(peer), repaired.peer_certificate_fingerprint()
            )
        finally:
            repaired.disconnect()


if __name__ == "__main__":
    unittest.main()
