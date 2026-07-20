import logging
import threading
import time

from .handshake import (
    DEFAULT_MANIFEST_PREPARATION_TIMEOUT,
    ManifestHandshakeQueue,
    RequestState,
)
from .executor import FifoTransferExecutor
from .status import TransferPhase
from .validation import ValidationError, validate_transfer_id


MAX_OUTGOING_MANIFESTS = 8
OUTGOING_MANIFEST_TIMEOUT = 30.0


logger = logging.getLogger(__name__)


class FilePasteService:
    def __init__(
        self,
        control,
        receiver,
        publisher,
        sender,
        snapshot_selection,
        executor=None,
        clock=time.monotonic,
        timer_factory=threading.Timer,
        preparation_timeout=DEFAULT_MANIFEST_PREPARATION_TIMEOUT,
        controller=None,
    ):
        self.control = control
        self.receiver = receiver
        self.publisher = publisher
        self.sender = sender
        self.controller = controller
        self.snapshot_selection = snapshot_selection
        self.executor = executor or FifoTransferExecutor(sender)
        self._clock = clock
        self._timer_factory = timer_factory
        self._preparation_timeout = float(preparation_timeout)
        self.handshakes = ManifestHandshakeQueue(
            self.control.send_message,
            clock=clock,
            timeout_seconds=self._preparation_timeout,
            timer_factory=timer_factory,
            on_state_change=self._on_handshake_state_change,
        )
        self._outgoing = {}
        self._outgoing_timers = {}
        self._outgoing_lock = threading.RLock()
        self._preparation = None
        self._outgoing_limit = MAX_OUTGOING_MANIFESTS
        self._outgoing_timeout = OUTGOING_MANIFEST_TIMEOUT
        register_callback = getattr(self.control, "register_callback", None)
        if callable(register_callback):
            register_callback("disconnected", self.on_disconnect)

    def request_paste(self):
        return self.handshakes.begin()

    def _on_handshake_state_change(self, request):
        if self.controller is None:
            return
        if request.state is RequestState.PENDING:
            self.controller.update(
                request.request_id,
                TransferPhase.PREPARING,
                "Files",
                0,
                0,
            )
            return
        if request.state is RequestState.ACCEPTED:
            self.controller.remove(request.request_id)
            return
        if request.state is RequestState.CANCELLED:
            self.controller.update(
                request.request_id,
                TransferPhase.CANCELLED,
                "Files",
                0,
                0,
            )
            return
        if request.state is RequestState.TIMED_OUT:
            error_code = "ManifestPreparationTimeout"
        elif request.error in {
            "ManifestLimitError",
            "ManifestPreparationTimeout",
        }:
            error_code = request.error
        else:
            error_code = "ManifestPreparationFailed"
        self.controller.update(
            request.request_id,
            TransferPhase.FAILED,
            "Files",
            0,
            0,
            error_code=error_code,
        )

    def on_manifest_request(self, message):
        request_id = message.get("request_id")
        try:
            validate_transfer_id(request_id, "request ID")
        except ValidationError:
            return False
        preparation = {
            "request_id": request_id,
            "deadline": self._clock() + self._preparation_timeout,
            "timer": None,
        }
        with self._outgoing_lock:
            at_limit = (
                self._preparation is not None
                or len(self._outgoing) >= self._outgoing_limit
            )
            if not at_limit:
                self._preparation = preparation
                self._schedule_preparation_expiry_locked(preparation)
        if at_limit:
            self.control.send_message({
                "type": "file_manifest_failed",
                "request_id": request_id,
                "error": "ManifestLimitError",
            })
            return False
        logger.info("Preparing file manifest: request_id=%s", request_id)
        try:
            worker = threading.Thread(
                target=self._prepare_manifest,
                args=(preparation, request_id),
                daemon=True,
            )
            worker.start()
        except Exception as error:
            with self._outgoing_lock:
                if self._preparation_is_current_locked(preparation, request_id):
                    self._send_preparation_failure_locked(request_id, error)
                    self._clear_preparation_request_locked(preparation)
                if self._preparation is preparation:
                    self._preparation = None
            return False
        return True

    def _prepare_manifest(self, preparation, request_id):
        retained_job_id = None
        try:
            manifest, sources = self.snapshot_selection()
            validate_transfer_id(manifest.job_id)
            with self._outgoing_lock:
                if not self._preparation_is_current_locked(
                    preparation, request_id
                ):
                    return False
                if manifest.job_id in self._outgoing:
                    raise ValueError("job ID is already awaiting acknowledgement")
                deadline = self._clock() + self._outgoing_timeout
                self._outgoing[manifest.job_id] = (manifest, sources, deadline)
                retained_job_id = manifest.job_id
                self._schedule_outgoing_expiry_locked(manifest.job_id)
                logger.info(
                    "Prepared file manifest: request_id=%s job_id=%s "
                    "file_count=%d total_bytes=%d",
                    request_id,
                    manifest.job_id,
                    manifest.file_count,
                    manifest.total_size,
                )
                sent = self.control.send_message({
                    "type": "file_manifest_response",
                    "request_id": request_id,
                    "manifest": manifest.to_wire(),
                })
                if not sent:
                    self._remove_outgoing_locked(manifest.job_id)
                return bool(sent)
        except Exception as error:
            with self._outgoing_lock:
                if retained_job_id is not None:
                    self._remove_outgoing_locked(retained_job_id)
                if self._preparation_is_current_locked(
                    preparation, request_id
                ):
                    self._send_preparation_failure_locked(request_id, error)
        finally:
            with self._outgoing_lock:
                if self._preparation_is_current_locked(
                    preparation, request_id
                ):
                    self._clear_preparation_request_locked(preparation)
                if self._preparation is preparation:
                    self._preparation = None

    def _preparation_is_current_locked(self, preparation, request_id):
        return (
            self._preparation is preparation
            and request_id is not None
            and preparation["request_id"] == request_id
        )

    def _schedule_preparation_expiry_locked(self, preparation, delay=None):
        timer = self._timer_factory(
            self._preparation_timeout if delay is None else delay,
            lambda: self._expire_preparation(preparation),
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        preparation["timer"] = timer
        timer.start()

    def _expire_preparation(self, preparation):
        with self._outgoing_lock:
            request_id = preparation["request_id"]
            if not self._preparation_is_current_locked(preparation, request_id):
                return False
            remaining = preparation["deadline"] - self._clock()
            if remaining > 0:
                self._schedule_preparation_expiry_locked(preparation, remaining)
                return False
            logger.info(
                "File manifest preparation expired: request_id=%s", request_id
            )
            try:
                self.control.send_message({
                    "type": "file_manifest_failed",
                    "request_id": request_id,
                    "error": "ManifestPreparationTimeout",
                })
            finally:
                self._clear_preparation_request_locked(preparation)
            return True

    def _send_preparation_failure_locked(self, request_id, error):
        error_name = type(error).__name__
        logger.info(
            "File manifest preparation failed: request_id=%s error=%s",
            request_id,
            error_name,
        )
        try:
            self.control.send_message({
                "type": "file_manifest_failed",
                "request_id": request_id,
                "error": error_name,
            })
        except Exception:
            logger.info(
                "Could not report file manifest preparation failure: "
                "request_id=%s",
                request_id,
            )

    @staticmethod
    def _clear_preparation_request_locked(preparation):
        # Hashing cannot be cancelled safely. Keep the preparation token until
        # its worker returns so retries cannot create unbounded hash threads.
        timer, preparation["timer"] = preparation["timer"], None
        if timer is not None:
            timer.cancel()
        preparation["request_id"] = None
        preparation["deadline"] = None

    def on_disconnect(self, message=None):
        self.handshakes.cancel_all()
        with self._outgoing_lock:
            preparation = self._preparation
            if preparation is not None and preparation["request_id"] is not None:
                logger.info(
                    "File manifest preparation cancelled on disconnect: "
                    "request_id=%s",
                    preparation["request_id"],
                )
                self._clear_preparation_request_locked(preparation)
            for timer in self._outgoing_timers.values():
                timer.cancel()
            self._outgoing_timers.clear()
            self._outgoing.clear()
        return True

    def on_manifest_response(self, message):
        request_id = message.get("request_id")
        manifest = message.get("manifest")
        if not self.handshakes.accept(request_id, manifest):
            return False
        try:
            self.receiver.accept_manifest(manifest)
        except Exception as error:
            logger.error(
                "File manifest response was rejected (%s)",
                type(error).__name__,
            )
            if self.controller is not None:
                self.controller.update(
                    request_id,
                    TransferPhase.FAILED,
                    "Files",
                    0,
                    0,
                    error_code="ManifestPreparationFailed",
                )
            return False
        self.control.send_message({
            "type": "file_manifest_ack",
            "job_id": manifest["job_id"],
        })
        self.publisher.publish_and_paste(manifest, self.receiver)
        return True

    def on_manifest_failed(self, message):
        return self.handshakes.fail(
            message.get("request_id"), message.get("error", "failed")
        )

    def on_manifest_ack(self, message):
        job_id = message.get("job_id")
        try:
            validate_transfer_id(job_id)
        except ValidationError:
            return False
        with self._outgoing_lock:
            outgoing = self._outgoing.pop(job_id, None)
            timer = self._outgoing_timers.pop(job_id, None)
            if timer is not None:
                timer.cancel()
        if outgoing is None:
            return False
        manifest, sources, deadline = outgoing
        if self._clock() > deadline:
            return False
        self.executor.submit(manifest, sources)
        return True

    def _schedule_outgoing_expiry_locked(self, job_id):
        timer = self._timer_factory(
            self._outgoing_timeout,
            lambda: self._expire_outgoing(job_id),
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        self._outgoing_timers[job_id] = timer
        timer.start()

    def _expire_outgoing(self, job_id):
        with self._outgoing_lock:
            outgoing = self._outgoing.get(job_id)
            if outgoing is None:
                return False
            remaining = outgoing[2] - self._clock()
            if remaining > 0:
                timer = self._timer_factory(
                    remaining, lambda: self._expire_outgoing(job_id)
                )
                if hasattr(timer, "daemon"):
                    timer.daemon = True
                self._outgoing_timers[job_id] = timer
                timer.start()
                return False
            self._outgoing.pop(job_id, None)
            self._outgoing_timers.pop(job_id, None)
            return True

    def _remove_outgoing_locked(self, job_id):
        outgoing = self._outgoing.pop(job_id, None)
        timer = self._outgoing_timers.pop(job_id, None)
        if timer is not None:
            timer.cancel()
        return outgoing
