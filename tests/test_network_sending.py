import threading
import time
import unittest

from app.network import NetworkNode


class OverlapDetectingSocket:
    def __init__(self):
        self.active = 0
        self.overlap = False
        self.started = threading.Event()
        self.release = threading.Event()

    def sendall(self, data):
        self.active += 1
        if self.active > 1:
            self.overlap = True
        self.started.set()
        self.release.wait(1)
        self.active -= 1


class NetworkSendingTests(unittest.TestCase):
    def test_concurrent_tls_messages_are_serialized(self):
        node = NetworkNode()
        node.connected = True
        node.sock = OverlapDetectingSocket()
        first = threading.Thread(target=lambda: node.send_message({"type": "first"}))
        second = threading.Thread(target=lambda: node.send_message({"type": "second"}))

        first.start()
        self.assertTrue(node.sock.started.wait(1))
        second.start()
        time.sleep(0.02)

        self.assertFalse(node.sock.overlap)
        node.sock.release.set()
        first.join(1)
        second.join(1)


if __name__ == "__main__":
    unittest.main()
