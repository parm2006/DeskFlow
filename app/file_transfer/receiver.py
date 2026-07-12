from pathlib import Path
import threading

from .compression import decode_chunk
from .models import ItemType, Manifest
from .staging import StagedFile
from .validation import validate_manifest, validate_relative_path


class TransferAbortedError(OSError):
    pass


class TransferReceiver:
    def __init__(self, staging_root):
        self.staging_root = Path(staging_root)
        self._jobs = {}

    def attach(self, lane):
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

    def accept_manifest(self, wire_manifest):
        manifest = validate_manifest(Manifest.from_wire(wire_manifest))
        if manifest.job_id in self._jobs:
            raise ValueError("job ID is already active")
        self._jobs[manifest.job_id] = {
            "manifest": manifest,
            "items": {item.relative_path: item for item in manifest.items},
            "staged": {},
            "condition": threading.Condition(),
            "completed": {},
            "error": None,
        }
        return manifest

    def accept_chunk(self, metadata, payload):
        job_id = metadata["job_id"]
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
            staged = job["staged"].get(relative_path)
            if staged is None:
                staged = StagedFile(
                    self.staging_root,
                    job_id,
                    relative_path,
                    item.size,
                    item.sha256,
                )
                job["staged"][relative_path] = staged
            staged.write(metadata["offset"], decoded)
            job["condition"].notify_all()

    def complete_file(self, job_id, relative_path):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        with job["condition"]:
            completed = job["staged"].pop(normalized).finalize()
            job["completed"][normalized] = completed
            job["condition"].notify_all()
            return completed

    def read_range(self, job_id, relative_path, offset, count):
        normalized = validate_relative_path(relative_path)
        job = self._jobs[job_id]
        item = job["items"][normalized]
        if offset >= item.size:
            return b""
        with job["condition"]:
            while True:
                completed = job["completed"].get(normalized)
                if completed is not None:
                    with completed.open("rb") as source:
                        source.seek(offset)
                        return source.read(min(count, item.size - offset))
                staged = job["staged"].get(normalized)
                if job["error"] is not None:
                    raise TransferAbortedError(job["error"])
                if staged is not None and staged.received_size > offset:
                    return staged.read_available(offset, count)
                job["condition"].wait()

    def cancel_job(self, job_id):
        job = self._jobs[job_id]
        with job["condition"]:
            for staged in job["staged"].values():
                staged.abort()
            job["staged"].clear()
            job["error"] = "transfer was cancelled"
            job["condition"].notify_all()

    def cancel_all(self, reason):
        for job_id in tuple(self._jobs):
            job = self._jobs[job_id]
            with job["condition"]:
                for staged in job["staged"].values():
                    staged.abort()
                job["staged"].clear()
                job["error"] = reason
                job["condition"].notify_all()
