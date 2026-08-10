import threading
import time

from .handshake import ManifestHandshakeQueue, RequestState
from .executor import FifoTransferExecutor
from .validation import ValidationError, validate_transfer_id


MAX_OUTGOING_MANIFESTS = 8
OUTGOING_MANIFEST_TIMEOUT = 30.0
_NO_CAPTURE = object()


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
        on_request_terminal=None,
        prepare_submit=None,
        capture_selection=None,
    ):
        self.control = control
        self.receiver = receiver
        self.publisher = publisher
        self.sender = sender
        self.snapshot_selection = snapshot_selection
        self.executor = executor or FifoTransferExecutor(sender)
        self.handshakes = ManifestHandshakeQueue(
            self.control.send_message,
            on_terminal=self._on_handshake_terminal,
        )
        self._outgoing = {}
        self._outgoing_timers = {}
        self._outgoing_lock = threading.Lock()
        self._destination_lock = threading.RLock()
        self._pending_snapshots = 0
        self._outgoing_limit = MAX_OUTGOING_MANIFESTS
        self._outgoing_timeout = OUTGOING_MANIFEST_TIMEOUT
        self._clock = clock
        self._timer_factory = timer_factory
        self.on_request_terminal = on_request_terminal
        self.prepare_submit = prepare_submit or self._submit_prepare
        self.capture_selection = capture_selection

    def request_paste(self):
        with self._destination_lock:
            return self.handshakes.begin()

    @property
    def destination_paste_active(self):
        with self._destination_lock:
            return (
                self.handshakes.has_pending
                or self.publisher.has_pending_paste
            )

    def on_manifest_request(self, message):
        request_id = message.get("request_id")
        try:
            validate_transfer_id(request_id, "request ID")
        except ValidationError:
            return False
        with self._outgoing_lock:
            at_limit = (
                len(self._outgoing) + self._pending_snapshots
                >= self._outgoing_limit
            )
            if not at_limit:
                self._pending_snapshots += 1
        if at_limit:
            self.control.send_message({
                "type": "file_manifest_failed",
                "request_id": request_id,
                "error": "ManifestLimitError",
            })
            return False
        preparing = {
            "type": "file_manifest_preparing",
            "request_id": request_id,
        }
        try:
            selection = (
                self.capture_selection()
                if self.capture_selection is not None
                else _NO_CAPTURE
            )
            if self.control.send_message(preparing) is False:
                with self._outgoing_lock:
                    self._pending_snapshots -= 1
                return False
            self.prepare_submit(
                lambda: self._prepare_manifest(request_id, selection)
            )
            return True
        except Exception as error:
            with self._outgoing_lock:
                self._pending_snapshots -= 1
            self.control.send_message({
                "type": "file_manifest_failed",
                "request_id": request_id,
                "error": type(error).__name__,
            })
            return False

    def _prepare_manifest(self, request_id, selection=_NO_CAPTURE):
        try:
            if selection is _NO_CAPTURE:
                manifest, sources = self.snapshot_selection()
            else:
                manifest, sources = self.snapshot_selection(selection)
            validate_transfer_id(manifest.job_id)
            with self._outgoing_lock:
                if manifest.job_id in self._outgoing:
                    raise ValueError("job ID is already awaiting acknowledgement")
                deadline = self._clock() + self._outgoing_timeout
                self._outgoing[manifest.job_id] = (manifest, sources, deadline)
                self._schedule_outgoing_expiry_locked(manifest.job_id)
            self.control.send_message({
                "type": "file_manifest_response",
                "request_id": request_id,
                "manifest": manifest.to_wire(),
            })
            return True
        except Exception as error:
            self.control.send_message({
                "type": "file_manifest_failed",
                "request_id": request_id,
                "error": type(error).__name__,
            })
            return False
        finally:
            with self._outgoing_lock:
                self._pending_snapshots -= 1

    @staticmethod
    def _submit_prepare(work):
        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        return thread

    def on_manifest_preparing(self, message):
        return self.handshakes.mark_preparing(message.get("request_id"))

    def on_manifest_response(self, message):
        with self._destination_lock:
            request_id = message.get("request_id")
            manifest = message.get("manifest")
            if not self.handshakes.accept(request_id, manifest):
                return False
            try:
                self.receiver.accept_manifest(manifest)
            except Exception as error:
                try:
                    self.control.send_message({
                        "type": "file_manifest_rejected",
                        "job_id": manifest.get("job_id"),
                        "error": type(error).__name__,
                    })
                finally:
                    if self.on_request_terminal is not None:
                        self.on_request_terminal()
                return False
            self.control.send_message({
                "type": "file_manifest_ack",
                "job_id": manifest["job_id"],
            })
            self.publisher.publish_and_paste(manifest, self.receiver)
            return True

    def on_manifest_failed(self, message):
        with self._destination_lock:
            return self.handshakes.fail(
                message.get("request_id"), message.get("error", "failed")
            )

    def _on_handshake_terminal(self, request):
        if (
            request.state in {RequestState.FAILED, RequestState.TIMED_OUT}
            and self.on_request_terminal is not None
        ):
            self.on_request_terminal()

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

    def on_manifest_rejected(self, message):
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
        return outgoing is not None

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
