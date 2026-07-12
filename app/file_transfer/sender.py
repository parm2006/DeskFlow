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
        if hasattr(lane, "register_callback"):
            lane.register_callback("job_verified", self._on_verified)

    def send_job(self, manifest, sources, announce_manifest=True):
        validate_manifest(manifest)
        label = _manifest_label(manifest)
        started = self.clock()
        bytes_done = 0
        self._update(manifest, TransferPhase.PREPARING, label, 0, 0)
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
                if compress:
                    self._update(manifest, TransferPhase.COMPRESSING, label, bytes_done, started)
                offset = 0
                for chunk in (() if first is None else (first,)):
                    self._check_cancelled(manifest.job_id)
                    offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
                    bytes_done += len(chunk)
                    self._update(manifest, TransferPhase.TRANSFERRING, label, bytes_done, started)
                for chunk in chunks:
                    self._check_cancelled(manifest.job_id)
                    offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
                    bytes_done += len(chunk)
                    self._update(manifest, TransferPhase.TRANSFERRING, label, bytes_done, started)
                self.lane.send({
                    "type": "file_complete",
                    "job_id": manifest.job_id,
                    "relative_path": item.relative_path,
                })
            verified = threading.Event()
            self._verified[manifest.job_id] = verified
            self._update(manifest, TransferPhase.VERIFYING, label, bytes_done, started)
            self.lane.send({"type": "job_complete", "job_id": manifest.job_id})
            if not verified.wait(30):
                raise TimeoutError("destination did not verify the file transfer")
            self._update(manifest, TransferPhase.COMPLETED, label, bytes_done, started)
        except TransferCancelled:
            self.lane.send({"type": "job_cancelled", "job_id": manifest.job_id})
            raise
        except Exception as error:
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

    def _update(self, manifest, phase, label, bytes_done, started):
        if not self.controller:
            return
        elapsed = max(0.0, self.clock() - started) if started else 0.0
        speed = bytes_done / elapsed if elapsed > 0 else 0.0
        self.controller.update(
            manifest.job_id,
            phase,
            label,
            bytes_done,
            manifest.total_size,
            speed,
        )


def _manifest_label(manifest):
    files = [item for item in manifest.items if item.item_type is ItemType.FILE]
    directories = [item for item in manifest.items if item.item_type is ItemType.DIRECTORY]
    if len(files) == 1 and not directories:
        return files[0].relative_path.rsplit("/", 1)[-1]
    if directories:
        return f"{len(directories)} folder{'s' if len(directories) != 1 else ''} + {len(files)} files"
    return f"{len(files)} files"
