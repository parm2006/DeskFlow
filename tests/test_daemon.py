import json
import tempfile
import threading
import unittest
from pathlib import Path

from app import daemon


class FakeServer:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.screen = None
        self.started = False
        self.stopped = False
        self.__class__.instances.append(self)

    def set_screen_size(self, width, height):
        self.screen = (width, height)

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


class FakeClient:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.screen = None
        self.connected = None
        self.disconnected = False
        self.__class__.instances.append(self)

    def set_screen_size(self, width, height):
        self.screen = (width, height)

    def connect(self, host, port, callback):
        self.connected = (host, port)
        callback(True, None)

    def disconnect(self):
        self.disconnected = True


class DaemonTests(unittest.TestCase):
    def setUp(self):
        FakeServer.instances.clear()
        FakeClient.instances.clear()

    def test_server_config_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "daemon.json"
            config.write_text(json.dumps({"role": "server", "password": "secret", "port": 6123, "layout": "left"}), encoding="utf-8")
            stop = threading.Event()
            stop.set()
            original = daemon._screen_size
            daemon._screen_size = lambda: (800, 600)
            try:
                self.assertEqual(daemon.run_daemon(["--config", str(config)], server_factory=FakeServer, stop_event=stop), 0)
            finally:
                daemon._screen_size = original
        service = FakeServer.instances[0]
        self.assertEqual(service.kwargs, {"password": "secret", "port": 6123, "layout_position": "left"})
        self.assertEqual(service.screen, (800, 600))
        self.assertTrue(service.started and service.stopped)

    def test_client_cli_and_lifecycle(self):
        stop = threading.Event()
        stop.set()
        original = daemon._screen_size
        daemon._screen_size = lambda: (1024, 768)
        try:
            self.assertEqual(daemon.run_daemon(["--role", "client", "--password", "pw", "--host", "10.0.0.2", "--port", "7000"], client_factory=FakeClient, stop_event=stop), 0)
        finally:
            daemon._screen_size = original
        service = FakeClient.instances[0]
        self.assertEqual(service.kwargs, {"password": "pw"})
        self.assertEqual(service.connected, ("10.0.0.2", 7000))
        self.assertEqual(service.screen, (1024, 768))
        self.assertTrue(service.disconnected)

    def test_missing_client_host_is_rejected(self):
        with self.assertRaises(SystemExit):
            daemon.run_daemon(["--role", "client", "--password", "pw"], client_factory=FakeClient, stop_event=threading.Event())

    def test_non_object_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "bad.json"
            config.write_text("[]", encoding="utf-8")
            with self.assertRaises(SystemExit):
                daemon.run_daemon(["--config", str(config)], server_factory=FakeServer, stop_event=threading.Event())
