from .compression import encode_chunk, should_compress
from .models import ItemType
from .validation import validate_manifest
from .status import TransferPhase
from .controller import TransferCancelled
import time
import threading


class TransferSender:
    def __init__(self, lane, controller=None, clock=time.monotonic):
        self.lane = lane
        self.controller = controller
        self.clock = clock
        self._verified = {}
        self._paste_jobs = {}
        self._paste_lock = threading.Lock()
        if hasattr(lane, "register_callback"):
            lane.register_callback("job_verified", self._on_verified)
            lane.register_callback("job_cancelled", self._on_cancelled)
            lane.register_callback("paste_progress", self._on_paste_progress)

    def send_job(self, manifest, sources, announce_manifest=True):
        validate_manifest(manifest)
        label = _manifest_label(manifest)
        bytes_done = 0
        with self._paste_lock:
            self._paste_jobs[manifest.job_id] = (label, manifest.total_size)
        self._waiting(manifest, label)
        if announce_manifest:
            self.lane.send({"type": "manifest", "manifest": manifest.to_wire()})
        try:
            for item in manifest.items:
                if item.item_type is ItemType.DIRECTORY:
                    continue
                source = sources[item.relative_path]
                if source.size != item.size or source.sha256 != item.sha256:
                    raise ValueError("source snapshot does not match the manifest")
                chunks = iter(source.iter_chunks())
                first = next(chunks, None)
                compress = bool(first) and should_compress(item.relative_path, item.size, first)
                offset = 0
                for chunk in (() if first is None else (first,)):
                    self._check_cancelled(manifest.job_id)
                    offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
                    bytes_done += len(chunk)
                for chunk in chunks:
                    self._check_cancelled(manifest.job_id)
                    offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
                    bytes_done += len(chunk)
                self.lane.send({
                    "type": "file_complete",
                    "job_id": manifest.job_id,
                    "relative_path": item.relative_path,
                })
            verified = threading.Event()
            self._verified[manifest.job_id] = verified
            self.lane.send({"type": "job_complete", "job_id": manifest.job_id})
            deadline = self.clock() + 30
            while not verified.wait(0.1):
                self._check_cancelled(manifest.job_id)
                if self.clock() >= deadline:
                    raise TimeoutError("destination did not verify the file transfer")
            self._waiting(manifest, label)
        except TransferCancelled:
            with self._paste_lock:
                self._paste_jobs.pop(manifest.job_id, None)
            self.lane.send({"type": "job_cancelled", "job_id": manifest.job_id})
            raise
        except Exception as error:
            with self._paste_lock:
                self._paste_jobs.pop(manifest.job_id, None)
            if self.controller:
                self.controller.update(
                    manifest.job_id, TransferPhase.FAILED, label, bytes_done,
                    manifest.total_size, error_code=type(error).__name__,
                )
            raise
        finally:
            self._verified.pop(manifest.job_id, None)

    def _on_verified(self, metadata, payload):
        event = self._verified.get(metadata.get("job_id"))
        if event is not None:
            event.set()

    def _on_cancelled(self, metadata, payload):
        job_id = metadata.get("job_id")
        if self.controller is not None:
            if self.controller.status(job_id) is not None:
                self.controller.cancel(job_id)
                self.controller.confirm_cancelled(job_id)
        event = self._verified.get(job_id)
        if event is not None:
            event.set()

    def _on_paste_progress(self, metadata, payload):
        job_id = metadata.get("job_id")
        with self._paste_lock:
            job = self._paste_jobs.get(job_id)
        if job is None:
            return False
        label, expected_total = job
        try:
            phase = TransferPhase(metadata.get("phase"))
            bytes_done = metadata.get("bytes_done")
            bytes_total = metadata.get("bytes_total")
            speed = metadata.get("bytes_per_second", 0.0)
            if phase not in {
                TransferPhase.PASTING,
                TransferPhase.COMPLETED,
                TransferPhase.CANCELLED,
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
            self.controller.update(job_id, phase, label, bytes_done, bytes_total, speed)
        if phase in {TransferPhase.COMPLETED, TransferPhase.CANCELLED}:
            with self._paste_lock:
                self._paste_jobs.pop(job_id, None)
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
