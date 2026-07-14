import logging
import threading
from collections import deque

from .controller import TransferCancelled
from app.safe_errors import error_name


logger = logging.getLogger(__name__)


class FifoTransferExecutor:
    def __init__(self, sender):
        self.sender = sender
        self._condition = threading.Condition()
        self._pending = deque()
        self._active = None
        self._started = set()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, manifest, sources):
        with self._condition:
            self._pending.append((manifest, sources))
            self._condition.notify_all()

    def wait_until_started(self, manifest, timeout=None):
        with self._condition:
            return self._condition.wait_for(
                lambda: manifest in self._started,
                timeout=timeout,
            )

    def wait_until_idle(self, timeout=None):
        with self._condition:
            return self._condition.wait_for(
                lambda: self._active is None and not self._pending,
                timeout=timeout,
            )

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: bool(self._pending))
                manifest, sources = self._pending.popleft()
                self._active = manifest
                self._started.add(manifest)
                self._condition.notify_all()
            try:
                self.sender.send_job(
                    manifest,
                    sources,
                    announce_manifest=False,
                )
            except TransferCancelled:
                logger.info("File transfer job cancelled")
            except Exception as error:
                logger.error("File transfer job failed (%s)", error_name(error))
            finally:
                with self._condition:
                    self._active = None
                    self._condition.notify_all()
