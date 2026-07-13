"""Headless DeskFlow runner for Windows user-session background operation."""
import argparse
import json
import logging
import signal
import threading

from app.client import DeskFlowClient
from app.server import DeskFlowServer

logger = logging.getLogger(__name__)


def _screen_size():
    try:
        import ctypes
        return (ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1))
    except Exception:
        return (1920, 1080)


def run_daemon(argv=None, server_factory=DeskFlowServer, client_factory=DeskFlowClient, stop_event=None):
    parser = argparse.ArgumentParser(prog="deskflow --daemon")
    parser.add_argument("--config", help="JSON file containing daemon options")
    parser.add_argument("--role", choices=("server", "client"))
    parser.add_argument("--password")
    parser.add_argument("--port", type=int)
    parser.add_argument("--layout")
    parser.add_argument("--host")
    parser.add_argument("--log-level")
    ns = parser.parse_args(argv)
    options = {}
    if ns.config:
        with open(ns.config, encoding="utf-8") as stream:
            options = json.load(stream)
        if not isinstance(options, dict):
            parser.error("--config must contain a JSON object")
    role = ns.role or options.get("role")
    password = ns.password or options.get("password")
    if role not in ("server", "client") or not password:
        parser.error("--role and --password are required (or provide them in --config)")
    logging.basicConfig(level=getattr(logging, str(ns.log_level or options.get("log_level", "INFO")).upper(), logging.INFO))
    stop_event = stop_event or threading.Event()
    # signal.signal is only valid on the main thread; injected events make the
    # lifecycle deterministic for embedders and tests.
    try:
        signal.signal(signal.SIGINT, lambda *_: stop_event.set())
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    except ValueError:
        logger.debug("daemon signal handlers unavailable outside main thread")
    width, height = _screen_size()
    service = None
    if role == "server":
        port = ns.port if ns.port is not None else options.get("port", 5000)
        service = server_factory(password=password, port=port, layout_position=ns.layout or options.get("layout", "right"))
        service.set_screen_size(width, height)
        if not service.start():
            raise RuntimeError("DeskFlow server failed to start")
    else:
        host = ns.host or options.get("host")
        if not host:
            parser.error("--host is required for client role")
        port = ns.port if ns.port is not None else options.get("port", 5000)
        service = client_factory(password=password)
        service.set_screen_size(width, height)
        connected = threading.Event()
        service.connect(host, port, lambda success, error: connected.set())
    try:
        stop_event.wait()
    finally:
        if service:
            (service.stop() if role == "server" else service.disconnect())
    return 0
