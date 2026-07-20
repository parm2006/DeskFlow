from pathlib import Path
import logging
import queue
import threading
import time
from collections import OrderedDict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.safe_errors import error_name

from .compression import MAX_CHUNK_SIZE, decode_chunk
from .models import ItemType, Manifest
from .staging import StagedFile, cleanup_staging_root
from .validation import (
    ValidationError,
    validate_manifest,
    validate_relative_path,
    validate_transfer_id,
)
from .status import TransferPhase
from .range_coverage import RangeCoverage


logger = logging.getLogger(__name__)
MAX_ACTIVE_JOBS = 8
_DROPEFFECT_COPY = 1

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
        self._jobs_lock = threading.RLock()
        self._terminal_jobs = OrderedDict()
        self._terminal_limit = 256
        self._terminal_lock = threading.Lock()
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
        lane.register_callback("job_failed", self._on_job_failed)

    def accept_manifest(self, wire_manifest):
        manifest = validate_manifest(Manifest.from_wire(wire_manifest))
        if self._terminal_reason(manifest.job_id) is not None:
            return None
        with self._jobs_lock:
            if manifest.job_id in self._jobs:
                raise ValueError("job ID is already active")
            if len(self._jobs) >= MAX_ACTIVE_JOBS:
                raise ValueError("active transfer limit reached")
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
            "drop_effect": None,
            "cleanup_generation": 0,
            "last_progress_bytes": -1,
            "last_progress_time": 0.0,
            "staging_key": AESGCM.generate_key(bit_length=256),
            }
        self._update_paste(manifest.job_id, TransferPhase.WAITING_FOR_EXPLORER, 0, 0.0)
        return manifest

    def accept_chunk(self, metadata, payload):
        job_id = metadata["job_id"]
        if self._terminal_reason(job_id) is not None:
            return False
        relative_path = validate_relative_path(metadata["relative_path"])
        job = self._jobs.get(job_id)
        if job is None:
            if self._terminal_reason(job_id) is not None:
                return False
            raise KeyError(job_id)
        item = job["items"][relative_path]
        if item.item_type is not ItemType.FILE:
            raise ValueError("directories cannot receive content chunks")
        decoded = decode_chunk(
            payload,
            metadata.get("compressed") is True,
            metadata["original_size"],
        )
        offset = metadata["offset"]
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("chunk offset must be a non-negative integer")
        with job["condition"]:
            if self._terminal_reason(job_id) is not None or job["error"] is not None:
                return False
            staged = job["staged"].get(relative_path)
            expected_offset = 0 if staged is None else staged.received_size
            if offset != expected_offset:
                raise ValueError(
                    f"chunk offset {offset} does not match expected offset {expected_offset}"
                )
            expected_chunk_size = min(MAX_CHUNK_SIZE, item.size - offset)
            if expected_chunk_size <= 0 or len(decoded) != expected_chunk_size:
                raise ValueError(
                    "chunk does not match the expected production chunk size"
                )
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
            staged.write(offset, decoded)
            job["bytes_received"] += len(decoded)
            job["condition"].notify_all()
        return True

    def complete_file(self, job_id, relative_path):
        if self._terminal_reason(job_id) is not None:
            return False
        normalized = validate_relative_path(relative_path)
        job = self._jobs.get(job_id)
        if job is None:
            if self._terminal_reason(job_id) is not None:
                return False
            raise KeyError(job_id)
        with job["condition"]:
            if self._terminal_reason(job_id) is not None or job["error"] is not None:
                return False
            staged = job["staged"].pop(normalized, None)
            if staged is None:
                item = job["items"][normalized]
                if item.item_type is not ItemType.FILE or item.size != 0:
                    raise ValueError("file completed before receiving content")
                staged = StagedFile(
                    self.staging_root,
                    job_id,
                    normalized,
                    item.size,
                    item.sha256,
                    encryption_key=job["staging_key"],
                )
            completed = staged.finalize()
            job["completed"][normalized] = completed
            job["condition"].notify_all()
            return completed

    def complete_job(self, job_id):
        if self._terminal_reason(job_id) is not None:
            return False
        job = self._jobs.get(job_id)
        if job is None:
            if self._terminal_reason(job_id) is not None:
                return False
            raise KeyError(job_id)
        with job["condition"]:
            if self._terminal_reason(job_id) is not None or job["error"] is not None:
                return False
            expected_files = {
                path for path, item in job["items"].items()
                if item.item_type is ItemType.FILE
            }
            if set(job["completed"]) != expected_files:
                raise ValueError("job completed before every file was verified")
            job["network_verified"] = True
            covered = self._paste_covered(job)
            phase = self._paste_phase(job, covered)
            if phase is TransferPhase.COMPLETED and not any(
                activity["active"] for activity in job["stream_activity"].values()
            ):
                cleanup_generation = self._next_cleanup_generation(job)
            else:
                cleanup_generation = None
        if phase is TransferPhase.WAITING_FOR_EXPLORER:
            self._update_paste(job_id, TransferPhase.WAITING_FOR_EXPLORER, 0, 0.0)
        else:
            self._publish_paste_progress(
                job_id,
                phase,
                covered,
                force=phase in {
                    TransferPhase.COMPLETED,
                    TransferPhase.VERIFYING_RESULT,
                },
            )
        if self.lane is not None:
            self.lane.send({"type": "job_verified", "job_id": job_id})
        if cleanup_generation is not None:
            self._schedule_terminal_cleanup(job_id, cleanup_generation)

    def record_stream_read(self, job_id, relative_path, offset, count):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        with job["condition"]:
            coverage = job["coverage"][normalized]
            coverage.add(offset, count)
            covered = self._paste_covered(job)
            if job["paste_started"] is None:
                job["paste_started"] = self.clock()
            phase = self._paste_phase(job, covered)
            if phase is TransferPhase.COMPLETED and not any(
                activity["active"] for activity in job["stream_activity"].values()
            ):
                cleanup_generation = self._next_cleanup_generation(job)
            else:
                cleanup_generation = None
        self._publish_paste_progress(
            job_id,
            phase,
            covered,
            force=phase in {
                TransferPhase.COMPLETED,
                TransferPhase.VERIFYING_RESULT,
            },
        )
        if cleanup_generation is not None:
            self._schedule_terminal_cleanup(job_id, cleanup_generation)

    def record_stream_open(self, job_id, relative_path):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        with job["condition"]:
            activity = job["stream_activity"][normalized]
            activity["active"] += 1
            activity["generation"] += 1
            job["cleanup_generation"] += 1

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
            incomplete = job["coverage"][normalized].covered < job["items"][normalized].size
            if activity["active"]:
                return True
            any_active = any(
                item_activity["active"]
                for item_activity in job["stream_activity"].values()
            )
            cleanup_generation = None
            abandon_path = normalized if incomplete else None
            if not incomplete and not any_active:
                if self._paste_phase(job) is TransferPhase.COMPLETED:
                    cleanup_generation = self._next_cleanup_generation(job)
                else:
                    abandon_path = next(
                        (
                            path for path, coverage in job["coverage"].items()
                            if coverage.covered < job["items"][path].size
                        ),
                        None,
                    )
            if abandon_path is None and cleanup_generation is None:
                return True
            generation = (
                None if abandon_path is None
                else job["stream_activity"][abandon_path]["generation"]
            )
        if cleanup_generation is not None:
            self._schedule_terminal_cleanup(job_id, cleanup_generation)
            return True
        timer = self.timer_factory(
            self.stream_close_grace,
            lambda: self._confirm_stream_abandoned(
                job_id, abandon_path, generation
            ),
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
            if any(
                item_activity["active"]
                for item_activity in job["stream_activity"].values()
            ):
                return False
            if job["coverage"][relative_path].covered >= job["items"][relative_path].size:
                return False
        current = self.controller.status(job_id) if self.controller is not None else None
        if current is not None and current.is_terminal:
            return False
        logger.info("Explorer released an incomplete file stream for job %s", job_id)
        return self.record_performed_drop(job_id, 0)

    def record_performed_drop(self, job_id, drop_effect):
        job = self._jobs.get(job_id)
        if job is None:
            return False
        with job["condition"]:
            if job["drop_effect"] is not None:
                return False
            job["drop_effect"] = drop_effect
            covered = self._paste_covered(job)
            copy_performed = bool(drop_effect & _DROPEFFECT_COPY)
            phase = (
                self._paste_phase(job, covered)
                if copy_performed
                else TransferPhase.CANCELLED
            )
            if phase is TransferPhase.COMPLETED and not any(
                activity["active"] for activity in job["stream_activity"].values()
            ):
                cleanup_generation = self._next_cleanup_generation(job)
            else:
                cleanup_generation = None
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
        if cleanup_generation is not None:
            self._schedule_terminal_cleanup(job_id, cleanup_generation)
        elif not copy_performed:
            self.cancel_job(job_id)
        return True

    @staticmethod
    def _next_cleanup_generation(job):
        job["cleanup_generation"] += 1
        return job["cleanup_generation"]

    def _schedule_terminal_cleanup(self, job_id, generation):
        timer = self.timer_factory(
            self.stream_close_grace,
            lambda: self._cleanup_terminal_job(job_id, generation),
        )
        if hasattr(timer, "daemon"):
            timer.daemon = True
        timer.start()

    def _cleanup_terminal_job(self, job_id, generation):
        job = self._jobs.get(job_id)
        if job is None:
            return False
        with job["condition"]:
            if (
                self._paste_phase(job) is not TransferPhase.COMPLETED
                or job["cleanup_generation"] != generation
                or any(
                    activity["active"]
                    for activity in job["stream_activity"].values()
                )
            ):
                return False
            for staged in job["staged"].values():
                staged.abort()
            for completed in job["completed"].values():
                completed.abort()
            job["staged"].clear()
            job["completed"].clear()
            job["error"] = "transfer cache was released"
            job["condition"].notify_all()
            if self._jobs.get(job_id) is job:
                self._jobs.pop(job_id, None)
        return True

    def read_range(self, job_id, relative_path, offset, count):
        normalized = validate_relative_path(relative_path)
        job = self._jobs.get(job_id)
        if job is None:
            reason = self._terminal_reason(job_id)
            if reason is not None:
                raise TransferAbortedError(reason)
            raise KeyError(job_id)
        item = job["items"][normalized]
        if count <= 0:
            return b""
        if offset >= item.size:
            return b""
        requested = min(count, item.size - offset)
        with job["condition"]:
            while True:
                if job["error"] is not None:
                    raise TransferAbortedError(job["error"])
                completed = job["completed"].get(normalized)
                if completed is not None:
                    staged = completed
                    break
                staged = job["staged"].get(normalized)
                if (
                    staged is not None
                    and staged.received_size >= offset + requested
                ):
                    break
                job["condition"].wait()
        # Authenticated decryption and disk I/O must not hold the receiver condition;
        # incoming chunks and cancellation remain responsive during Explorer reads.
        return staged.read_available(offset, requested)

    def cancel_job(self, job_id):
        job = self._jobs.get(job_id)
        if job is None:
            self._remember_terminal(job_id, "transfer was cancelled")
            return False
        with job["condition"]:
            self._remember_terminal(job_id, "transfer was cancelled")
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
            if self._jobs.get(job_id) is job:
                self._jobs.pop(job_id, None)
        return True

    def fail_paste(self, job_id, error_code):
        return self._fail_job(
            job_id,
            error_code,
            "Windows Explorer did not accept the file paste",
            notify_peer=True,
        )

    def _on_job_failed(self, metadata, payload):
        if payload or metadata.get("error_code") != "SourceReadFailed":
            return False
        job_id = metadata.get("job_id")
        try:
            validate_transfer_id(job_id)
        except ValidationError:
            return False
        return self._fail_job(
            job_id,
            "SourceReadFailed",
            "the source could not read the selected file",
            notify_peer=False,
        )

    def _fail_job(self, job_id, error_code, reason, notify_peer):
        job = self._jobs.get(job_id)
        if job is None:
            return False
        current = self.controller.status(job_id) if self.controller is not None else None
        if current is not None and current.is_terminal:
            return False
        with job["condition"]:
            if job["error"] is not None:
                return False
            for staged in job["staged"].values():
                staged.abort()
            for completed in job["completed"].values():
                completed.abort()
            job["staged"].clear()
            job["completed"].clear()
            job["error"] = reason
            job["condition"].notify_all()
        manifest = job["manifest"]
        if self.controller is not None:
            self.controller.update(
                job_id,
                TransferPhase.FAILED,
                _manifest_label(manifest),
                self._paste_covered(job),
                manifest.total_size,
                error_code=error_code,
            )
        if notify_peer and self.lane is not None:
            self._progress_queue.put({
                "type": "paste_progress",
                "job_id": job_id,
                "phase": TransferPhase.FAILED.value,
                "bytes_done": self._paste_covered(job),
                "bytes_total": manifest.total_size,
                "bytes_per_second": 0.0,
                "error_code": error_code,
            })
        self._remember_terminal(job_id, reason)
        if self._jobs.get(job_id) is job:
            self._jobs.pop(job_id, None)
        return True

    def is_paste_terminal(self, job_id):
        if self._terminal_reason(job_id) is not None:
            return True
        status = self.controller.status(job_id) if self.controller is not None else None
        return status is not None and status.is_terminal

    def _terminal_reason(self, job_id):
        with self._terminal_lock:
            return self._terminal_jobs.get(job_id)

    def _remember_terminal(self, job_id, reason):
        with self._terminal_lock:
            self._terminal_jobs[job_id] = reason
            self._terminal_jobs.move_to_end(job_id)
            while len(self._terminal_jobs) > self._terminal_limit:
                self._terminal_jobs.popitem(last=False)

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
            manifest.total_size
            if phase in {
                TransferPhase.PASTING,
                TransferPhase.VERIFYING_RESULT,
                TransferPhase.COMPLETED,
            }
            else 0,
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

    @classmethod
    def _paste_phase(cls, job, covered=None):
        if covered is None:
            covered = cls._paste_covered(job)
        total_size = job["manifest"].total_size
        copy_performed = (
            job["drop_effect"] is not None
            and bool(job["drop_effect"] & _DROPEFFECT_COPY)
        )
        if job["network_verified"] and copy_performed and covered == total_size:
            return TransferPhase.COMPLETED
        if job["network_verified"] and total_size > 0 and covered == total_size:
            return TransferPhase.VERIFYING_RESULT
        if covered:
            return TransferPhase.PASTING
        return TransferPhase.WAITING_FOR_EXPLORER

    def cancel_all(self, reason):
        for job_id, job in tuple(self._jobs.items()):
            with job["condition"]:
                for staged in job["staged"].values():
                    staged.abort()
                for completed in job["completed"].values():
                    completed.abort()
                job["staged"].clear()
                job["completed"].clear()
                job["error"] = reason
                job["condition"].notify_all()
                self._remember_terminal(job_id, reason)
                if self.controller is not None:
                    status = self.controller.status(job_id)
                    if status is not None and not status.is_terminal:
                        self.controller.cancel(job_id)
                        self.controller.confirm_cancelled(job_id)
                if self._jobs.get(job_id) is job:
                    self._jobs.pop(job_id, None)


def _manifest_label(manifest):
    files = [item for item in manifest.items if item.item_type is ItemType.FILE]
    directories = [item for item in manifest.items if item.item_type is ItemType.DIRECTORY]
    if len(files) == 1 and not directories:
        return files[0].relative_path.rsplit("/", 1)[-1]
    if directories:
        return f"{len(directories)} folder{'s' if len(directories) != 1 else ''} + {len(files)} files"
    return f"{len(files)} files"
