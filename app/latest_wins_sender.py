import logging
import threading
import time

from app.safe_errors import error_name


logger = logging.getLogger(__name__)


class LatestWinsSender:
    """Send one payload at a time while retaining only the newest pending one."""

    def __init__(self, send):
        self._send = send
        self._condition = threading.Condition()
        self._pending = None
        self._sending = False
        self._stopped = False
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, payload):
        snapshot = dict(payload)
        with self._condition:
            if self._stopped:
                return False
            self._pending = snapshot
            self._condition.notify()
            return True

    @property
    def stopped(self):
        with self._condition:
            return self._stopped

    def wait_until_idle(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._sending or self._pending is not None:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def stop(self):
        with self._condition:
            self._stopped = True
            self._pending = None
            self._condition.notify_all()
        if threading.current_thread() is not self._worker:
            self._worker.join(timeout=1)

    def _run(self):
        while True:
            with self._condition:
                while self._pending is None and not self._stopped:
                    self._condition.wait()
                if self._stopped:
                    return
                payload = self._pending
                self._pending = None
                self._sending = True

            retry = False
            try:
                retry = self._send(payload) is False
            except Exception as error:
                logger.error("Latest-wins send failed (%s)", error_name(error))
            finally:
                with self._condition:
                    self._sending = False
                    if retry and not self._stopped and self._pending is None:
                        self._pending = payload
                    self._condition.notify_all()
                    if retry and not self._stopped:
                        self._condition.wait(timeout=0.1)
