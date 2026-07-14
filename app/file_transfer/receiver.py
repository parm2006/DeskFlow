from pathlib import Path
import logging
import queue
import threading
import time
from collections import OrderedDict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.safe_errors import error_name

from .compression import decode_chunk
from .models import ItemType, Manifest
from .staging import StagedFile, cleanup_staging_root
from .validation import validate_manifest, validate_relative_path
from .status import TransferPhase
from .range_coverage import RangeCoverage


logger = logging.getLogger(__name__)

class TransferAbortedError(OSError):
    winerror = 1223


class TransferReceiver:
    def __init__(
        self, staging_root, controller=None, clock=time.monotonic,
        timer_factory=threading.Timer, stream_close_grace=1.0,
    ):
        self.staging_root = Path(staging_root)
        cleanup_staging_root(self.staging_root)
        self.controller = controller
        self.clock = clock
        self.timer_factory = timer_factory
        self.stream_close_grace = stream_close_grace
        self.lane = None
        self._jobs = {}
        self._cancelled_jobs = OrderedDict()
        self._cancelled_limit = 256
        self._progress_queue = queue.Queue()
        self._progress_worker = None

    def attach(self, lane):
        self.lane = lane
        if self._progress_worker is None:
            self._progress_worker = threading.Thread(target=self._send_progress, daemon=True)
            self._progress_worker.start()
        lane.register_callback(
            "manifest", lambda metadata, payload: self.accept_manifest(metadata["manifest"])
        )
        lane.register_callback(
            "disconnected", lambda metadata, payload: self.cancel_all("file lane disconnected")
        )
        lane.register_callback(
            "chunk", lambda metadata, payload: self.accept_chunk(metadata, payload)
        )
        lane.register_callback(
            "file_complete",
            lambda metadata, payload: self.complete_file(
                metadata["job_id"], metadata["relative_path"]
            ),
        )
        lane.register_callback(
            "job_complete", lambda metadata, payload: self.complete_job(metadata["job_id"])
        )

    def accept_manifest(self, wire_manifest):
        manifest = validate_manifest(Manifest.from_wire(wire_manifest))
        if manifest.job_id in self._cancelled_jobs:
            return None
        if manifest.job_id in self._jobs:
            raise ValueError("job ID is already active")
        self._jobs[manifest.job_id] = {
            "manifest": manifest,
            "items": {item.relative_path: item for item in manifest.items},
            "staged": {},
            "condition": threading.Condition(),
            "completed": {},
            "error": None,
            "bytes_received": 0,
            "started": self.clock(),
            "coverage": {
                item.relative_path: RangeCoverage(item.size)
                for item in manifest.items if item.item_type is ItemType.FILE
            },
            "stream_activity": {
                item.relative_path: {"active": 0, "generation": 0}
                for item in manifest.items if item.item_type is ItemType.FILE
            },
            "paste_started": None,
            "network_verified": False,
            "last_progress_bytes": -1,
            "last_progress_time": 0.0,
            "staging_key": AESGCM.generate_key(bit_length=256),
        }
        self._update_paste(manifest.job_id, TransferPhase.WAITING_FOR_EXPLORER, 0, 0.0)
        return manifest

    def accept_chunk(self, metadata, payload):
        job_id = metadata["job_id"]
        if job_id in self._cancelled_jobs:
            return False
        relative_path = validate_relative_path(metadata["relative_path"])
        job = self._jobs[job_id]
        item = job["items"][relative_path]
        if item.item_type is not ItemType.FILE:
            raise ValueError("directories cannot receive content chunks")
        decoded = decode_chunk(
            payload,
            metadata.get("compressed") is True,
            metadata["original_size"],
        )
        with job["condition"]:
            if job_id in self._cancelled_jobs or job["error"] is not None:
                return False
            staged = job["staged"].get(relative_path)
            if staged is None:
                staged = StagedFile(
                    self.staging_root,
                    job_id,
                    relative_path,
                    item.size,
                    item.sha256,
                    encryption_key=job["staging_key"],
                )
                job["staged"][relative_path] = staged
            staged.write(metadata["offset"], decoded)
            job["bytes_received"] += len(decoded)
            job["condition"].notify_all()
        return True

    def complete_file(self, job_id, relative_path):
        if job_id in self._cancelled_jobs:
            return False
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        with job["condition"]:
            if job_id in self._cancelled_jobs or job["error"] is not None:
                return False
            completed = job["staged"].pop(normalized).finalize()
            job["completed"][normalized] = completed
            job["condition"].notify_all()
            return completed

    def complete_job(self, job_id):
        if job_id in self._cancelled_jobs:
            return False
        job = self._jobs[job_id]
        with job["condition"]:
            if job_id in self._cancelled_jobs or job["error"] is not None:
                return False
            expected_files = {
                path for path, item in job["items"].items()
                if item.item_type is ItemType.FILE
            }
            if set(job["completed"]) != expected_files:
                raise ValueError("job completed before every file was verified")
            job["network_verified"] = True
        covered = self._paste_covered(job)
        if covered == job["manifest"].total_size:
            self._publish_paste_progress(job_id, TransferPhase.COMPLETED, covered, force=True)
        elif covered:
            self._publish_paste_progress(job_id, TransferPhase.PASTING, covered, force=True)
        else:
            self._update_paste(job_id, TransferPhase.WAITING_FOR_EXPLORER, 0, 0.0)
        if self.lane is not None:
            self.lane.send({"type": "job_verified", "job_id": job_id})

    def record_stream_read(self, job_id, relative_path, offset, count):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        coverage = job["coverage"][normalized]
        coverage.add(offset, count)
        covered = self._paste_covered(job)
        if job["paste_started"] is None:
            job["paste_started"] = self.clock()
        phase = (
            TransferPhase.COMPLETED
            if job["network_verified"] and covered == job["manifest"].total_size
            else TransferPhase.PASTING
        )
        self._publish_paste_progress(job_id, phase, covered, force=phase is TransferPhase.COMPLETED)

    def record_stream_open(self, job_id, relative_path):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        with job["condition"]:
            activity = job["stream_activity"][normalized]
            activity["active"] += 1
            activity["generation"] += 1

    def record_stream_close(self, job_id, relative_path):
        normalized = validate_relative_path(relative_path)
        job = self._jobs.get(job_id)
        if job is None:
            return False
        with job["condition"]:
            activity = job["stream_activity"][normalized]
            if activity["active"] <= 0:
                return False
            activity["active"] -= 1
            activity["generation"] += 1
            generation = activity["generation"]
            incomplete = job["coverage"][normalized].covered < job["items"][normalized].size
            if activity["active"] or not incomplete:
                return True
        timer = self.timer_factory(
            self.stream_close_grace,
            lambda: self._confirm_stream_abandoned(job_id, normalized, generation),
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        timer.start()
        return True

    def _confirm_stream_abandoned(self, job_id, relative_path, generation):
        job = self._jobs.get(job_id)
        if job is None:
            return False
        with job["condition"]:
            activity = job["stream_activity"][relative_path]
            if activity["active"] or activity["generation"] != generation:
                return False
            if job["coverage"][relative_path].covered >= job["items"][relative_path].size:
                return False
        current = self.controller.status(job_id) if self.controller is not None else None
        if current is not None and current.is_terminal:
            return False
        logger.info("Explorer released an incomplete file stream for job %s", job_id)
        return self.record_performed_drop(job_id)

    def record_performed_drop(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            return False
        covered = self._paste_covered(job)
        phase = (
            TransferPhase.COMPLETED
            if job["network_verified"] and covered == job["manifest"].total_size
            else TransferPhase.CANCELLED
        )
        self._update_paste(job_id, phase, covered, 0.0)
        if self.lane is not None:
            self._progress_queue.put({
                "type": "paste_progress",
                "job_id": job_id,
                "phase": phase.value,
                "bytes_done": covered,
                "bytes_total": job["manifest"].total_size,
                "bytes_per_second": 0.0,
            })
        return True

    def read_range(self, job_id, relative_path, offset, count):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        item = job["items"][normalized]
        if offset >= item.size:
            return b""
        with job["condition"]:
            while True:
                if job["error"] is not None:
                    raise TransferAbortedError(job["error"])
                completed = job["completed"].get(normalized)
                if completed is not None:
                    staged = completed
                    break
                staged = job["staged"].get(normalized)
                if staged is not None and staged.received_size > offset:
                    break
                job["condition"].wait()
        # Authenticated decryption and disk I/O must not hold the receiver condition;
        # incoming chunks and cancellation remain responsive during Explorer reads.
        return staged.read_available(offset, min(count, item.size - offset))

    def cancel_job(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            self._remember_cancelled(job_id)
            return False
        with job["condition"]:
            self._remember_cancelled(job_id)
            for staged in job["staged"].values():
                staged.abort()
            for completed in job["completed"].values():
                completed.abort()
            job["staged"].clear()
            job["completed"].clear()
            job["error"] = "transfer was cancelled"
            if self.controller is not None:
                self.controller.cancel(job_id)
            job["condition"].notify_all()
        return True

    def _remember_cancelled(self, job_id):
        self._cancelled_jobs[job_id] = None
        self._cancelled_jobs.move_to_end(job_id)
        while len(self._cancelled_jobs) > self._cancelled_limit:
            self._cancelled_jobs.popitem(last=False)

    def _update_paste(self, job_id, phase, bytes_done, speed):
        if self.controller is None:
            return
        job = self._jobs[job_id]
        manifest = job["manifest"]
        self.controller.update(
            job_id,
            phase,
            _manifest_label(manifest),
            bytes_done,
            manifest.total_size if phase is TransferPhase.PASTING or phase is TransferPhase.COMPLETED else 0,
            speed,
        )

    def _publish_paste_progress(self, job_id, phase, covered, force=False):
        job = self._jobs[job_id]
        now = self.clock()
        elapsed = max(0.0, now - job["paste_started"]) if job["paste_started"] is not None else 0.0
        speed = covered / elapsed if elapsed > 0 else 0.0
        enough_bytes = covered - job["last_progress_bytes"] >= 1 << 20
        enough_time = now - job["last_progress_time"] >= 0.1
        if not (force or job["last_progress_bytes"] < 0 or enough_bytes or enough_time):
            return
        job["last_progress_bytes"] = covered
        job["last_progress_time"] = now
        self._update_paste(job_id, phase, covered, speed)
        if self.lane is not None:
            self._progress_queue.put({
                "type": "paste_progress",
                "job_id": job_id,
                "phase": phase.value,
                "bytes_done": covered,
                "bytes_total": job["manifest"].total_size,
                "bytes_per_second": speed,
            })

    def _send_progress(self):
        while True:
            metadata = self._progress_queue.get()
            try:
                self.lane.send(metadata)
            except Exception as error:
                logger.error(
                    "Could not send Explorer paste progress (%s)",
                    error_name(error),
                )

    @staticmethod
    def _paste_covered(job):
        return sum(coverage.covered for coverage in job["coverage"].values())

    def cancel_all(self, reason):
        for job_id in tuple(self._jobs):
            job = self._jobs[job_id]
            with job["condition"]:
                for staged in job["staged"].values():
                    staged.abort()
                for completed in job["completed"].values():
                    completed.abort()
                job["staged"].clear()
                job["completed"].clear()
                job["error"] = reason
                job["condition"].notify_all()


def _manifest_label(manifest):
    files = [item for item in manifest.items if item.item_type is ItemType.FILE]
    directories = [item for item in manifest.items if item.item_type is ItemType.DIRECTORY]
    if len(files) == 1 and not directories:
        return files[0].relative_path.rsplit("/", 1)[-1]
    if directories:
        return f"{len(directories)} folder{'s' if len(directories) != 1 else ''} + {len(files)} files"
    return f"{len(files)} files"
