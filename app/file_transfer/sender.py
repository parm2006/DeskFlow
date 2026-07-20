from collections import OrderedDict
from .compression import encode_chunk, should_compress
from .models import ItemType
from .validation import ValidationError, validate_manifest, validate_transfer_id
from .status import TransferPhase
from .controller import TransferCancelled
import time
import threading


class DestinationPasteError(RuntimeError):
    pass


SAFE_DESTINATION_ERROR_CODES = frozenset((
    "ClipboardPublishFailed",
    "PasteInjectionFailed",
    "ExplorerStartTimeout",
))


def _safe_destination_error_code(value):
    return value if value in SAFE_DESTINATION_ERROR_CODES else "DestinationPasteFailed"


class TransferSender:
    def __init__(self, lane, controller=None, clock=time.monotonic):
        self.lane = lane
        self.controller = controller
        self.clock = clock
        self._verified = {}
        self._active_send_terminals = {}
        self._paste_jobs = {}
        self._early_paste_terminal = OrderedDict()
        self._early_paste_limit = 256
        self._paste_lock = threading.Lock()
        if hasattr(lane, "register_callback"):
            lane.register_callback("job_verified", self._on_verified)
            lane.register_callback("paste_progress", self._on_paste_progress)

    def send_job(self, manifest, sources, announce_manifest=True):
        validate_manifest(manifest)
        label = _manifest_label(manifest)
        failure_label = label
        bytes_done = 0
        with self._paste_lock:
            self._paste_jobs[manifest.job_id] = (label, manifest.total_size)
            early_terminal = self._early_paste_terminal.pop(manifest.job_id, None)
            self._active_send_terminals[manifest.job_id] = early_terminal
        try:
            self._waiting(manifest, label)
            if announce_manifest:
                self.lane.send({"type": "manifest", "manifest": manifest.to_wire()})
            if early_terminal is not None:
                self._on_paste_progress(early_terminal, b"")
            self._check_terminal(manifest.job_id)
            for item in manifest.items:
                if item.item_type is ItemType.DIRECTORY:
                    continue
                failure_label = item.relative_path.rsplit("/", 1)[-1]
                try:
                    source = sources[item.relative_path]
                    if source.size != item.size or source.sha256 != item.sha256:
                        raise ValueError("source snapshot does not match the manifest")
                except Exception:
                    self._notify_peer_source_failure(manifest.job_id)
                    raise
                chunks = iter(self._read_source_chunks(manifest.job_id, source))
                try:
                    first = next(chunks, None)
                    compress = bool(first) and should_compress(item.relative_path, item.size, first)
                    offset = 0
                    for chunk in (() if first is None else (first,)):
                        self._check_terminal(manifest.job_id)
                        offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
                        bytes_done += len(chunk)
                        self._check_terminal(manifest.job_id)
                    for chunk in chunks:
                        self._check_terminal(manifest.job_id)
                        offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
                        bytes_done += len(chunk)
                        self._check_terminal(manifest.job_id)
                finally:
                    chunks.close()
                self.lane.send({
                    "type": "file_complete",
                    "job_id": manifest.job_id,
                    "relative_path": item.relative_path,
                })
                self._check_terminal(manifest.job_id)
            failure_label = label
            verified = threading.Event()
            with self._paste_lock:
                self._verified[manifest.job_id] = verified
            self._check_terminal(manifest.job_id)
            self.lane.send({"type": "job_complete", "job_id": manifest.job_id})
            self._check_terminal(manifest.job_id)
            deadline = self.clock() + 30
            while not verified.wait(0.05):
                self._check_terminal(manifest.job_id)
                if self.clock() >= deadline:
                    raise TimeoutError("destination did not verify the file transfer")
            self._check_terminal(manifest.job_id)
            self._waiting(manifest, label)
        except TransferCancelled:
            with self._paste_lock:
                self._paste_jobs.pop(manifest.job_id, None)
            raise
        except Exception as error:
            with self._paste_lock:
                self._paste_jobs.pop(manifest.job_id, None)
            if self.controller:
                self.controller.update(
                    manifest.job_id, TransferPhase.FAILED, failure_label, bytes_done,
                    manifest.total_size, error_code=type(error).__name__,
                )
            raise
        finally:
            with self._paste_lock:
                self._verified.pop(manifest.job_id, None)
                self._active_send_terminals.pop(manifest.job_id, None)

    def _on_verified(self, metadata, payload):
        with self._paste_lock:
            event = self._verified.get(metadata.get("job_id"))
        if event is not None:
            event.set()

    def _on_paste_progress(self, metadata, payload):
        job_id = metadata.get("job_id")
        try:
            validate_transfer_id(job_id)
        except ValidationError:
            return False
        try:
            phase = TransferPhase(metadata.get("phase"))
        except (TypeError, ValueError):
            return False
        with self._paste_lock:
            job = self._paste_jobs.get(job_id)
        if job is None:
            if phase not in {TransferPhase.FAILED, TransferPhase.CANCELLED}:
                return False
            bytes_done = metadata.get("bytes_done")
            bytes_total = metadata.get("bytes_total")
            speed = metadata.get("bytes_per_second", 0.0)
            if (
                not isinstance(job_id, str)
                or not isinstance(bytes_done, int) or bytes_done < 0
                or not isinstance(bytes_total, int) or bytes_total < bytes_done
                or not isinstance(speed, (int, float)) or speed < 0
            ):
                return False
            with self._paste_lock:
                self._early_paste_terminal[job_id] = dict(metadata)
                self._early_paste_terminal.move_to_end(job_id)
                while len(self._early_paste_terminal) > self._early_paste_limit:
                    self._early_paste_terminal.popitem(last=False)
            return True
        label, expected_total = job
        try:
            bytes_done = metadata.get("bytes_done")
            bytes_total = metadata.get("bytes_total")
            speed = metadata.get("bytes_per_second", 0.0)
            if phase not in {
                TransferPhase.PASTING,
                TransferPhase.VERIFYING_RESULT,
                TransferPhase.COMPLETED,
                TransferPhase.CANCELLED,
                TransferPhase.FAILED,
            }:
                return False
            if not isinstance(bytes_done, int) or not 0 <= bytes_done <= expected_total:
                return False
            if bytes_total != expected_total or not isinstance(speed, (int, float)) or speed < 0:
                return False
        except (TypeError, ValueError):
            return False
        current = self.controller.status(job_id) if self.controller else None
        if current is not None and bytes_done < current.bytes_done:
            return False
        if self.controller:
            self.controller.update(
                job_id, phase, label, bytes_done, bytes_total, speed,
                error_code=(
                    _safe_destination_error_code(metadata.get("error_code"))
                    if phase is TransferPhase.FAILED
                    else None
                ),
            )
        if phase in {
            TransferPhase.COMPLETED,
            TransferPhase.CANCELLED,
            TransferPhase.FAILED,
        }:
            with self._paste_lock:
                active_send = job_id in self._active_send_terminals
                if phase in {TransferPhase.CANCELLED, TransferPhase.FAILED} and active_send:
                    if self._active_send_terminals[job_id] is None:
                        self._active_send_terminals[job_id] = dict(metadata)
                    verified = self._verified.get(job_id)
                else:
                    self._paste_jobs.pop(job_id, None)
                    verified = None
            if verified is not None:
                verified.set()
        return True

    def _waiting(self, manifest, label):
        if self.controller:
            current = self.controller.status(manifest.job_id)
            if current is not None and current.phase in {
                TransferPhase.PASTING,
                TransferPhase.VERIFYING_RESULT,
                TransferPhase.CANCELLING,
            }:
                return
            self.controller.update(
                manifest.job_id, TransferPhase.WAITING_FOR_EXPLORER,
                label, 0, 0, 0.0,
            )

    def _send_chunk(self, job_id, relative_path, offset, chunk, compress):
        encoded = encode_chunk(chunk, compress)
        self.lane.send(
            {
                "type": "chunk",
                "job_id": job_id,
                "relative_path": relative_path,
                "offset": offset,
                "compressed": encoded.compressed,
                "original_size": encoded.original_size,
            },
            encoded.data,
        )
        return offset + len(chunk)

    def _read_source_chunks(self, job_id, source):
        try:
            yield from source.iter_chunks()
        except Exception:
            self._notify_peer_source_failure(job_id)
            raise

    def _notify_peer_source_failure(self, job_id):
        try:
            self.lane.send({
                "type": "job_failed",
                "job_id": job_id,
                "error_code": "SourceReadFailed",
            })
        except Exception:
            # The source error remains the actionable local failure if the lane
            # is no longer available to notify the peer.
            pass

    def _check_terminal(self, job_id):
        with self._paste_lock:
            terminal = self._active_send_terminals.get(job_id)
        if terminal is not None:
            phase = TransferPhase(terminal["phase"])
            if phase is TransferPhase.CANCELLED:
                raise TransferCancelled(job_id)
            raise DestinationPasteError(
                _safe_destination_error_code(terminal.get("error_code"))
            )
        self._check_cancelled(job_id)

    def _check_cancelled(self, job_id):
        if self.controller:
            self.controller.check_cancelled(job_id)

def _manifest_label(manifest):
    files = [item for item in manifest.items if item.item_type is ItemType.FILE]
    directories = [item for item in manifest.items if item.item_type is ItemType.DIRECTORY]
    if len(files) == 1 and not directories:
        return files[0].relative_path.rsplit("/", 1)[-1]
    if directories:
        return f"{len(directories)} folder{'s' if len(directories) != 1 else ''} + {len(files)} files"
    return f"{len(files)} files"
