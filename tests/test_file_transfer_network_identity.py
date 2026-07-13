import hashlib
import unittest

from app.network import NetworkNode


class FakeTlsSocket:
    def __init__(self, certificate):
        self.certificate = certificate

    def getpeercert(self, binary_form=False):
        return self.certificate if binary_form else {}


class NetworkIdentityTests(unittest.TestCase):
    def test_reads_live_peer_certificate_fingerprint(self):
        node = NetworkNode()
        node.sock = FakeTlsSocket(b"control peer certificate")

        self.assertEqual(
            node.peer_certificate_fingerprint(),
            hashlib.sha256(b"control peer certificate").hexdigest(),
        )

    def test_requires_a_live_tls_peer_certificate(self):
        node = NetworkNode()
        with self.assertRaises(RuntimeError):
            node.peer_certificate_fingerprint()


if __name__ == "__main__":
    unittest.main()
