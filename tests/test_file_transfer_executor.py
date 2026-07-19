import threading
import tempfile
import unittest
from pathlib import Path

from app.file_transfer.controller import TransferCancelled
from app.file_transfer.executor import FifoTransferExecutor
from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.sender import TransferSender
from app.file_transfer.source import SourceFile


class BlockingSender:
    def __init__(self):
        self.started = []
        self.finished = []
        self.release_first = threading.Event()

    def send_job(self, manifest, sources, announce_manifest=False):
        self.started.append(manifest)
        if manifest == "A":
            self.release_first.wait(1)
        self.finished.append(manifest)


class FifoTransferExecutorTests(unittest.TestCase):
    def test_real_sender_releases_exactly_one_job_per_terminal_ack(self):
        class Lane:
            def __init__(self):
                self.callbacks = {}

            def register_callback(self, name, callback):
                self.callbacks.setdefault(name, []).append(callback)

            def send(self, metadata, payload=b""):
                if metadata["type"] == "job_complete":
                    verified = {
                        "type": "job_verified",
                        "job_id": metadata["job_id"],
                    }
                    for callback in self.callbacks.get("job_verified", ()):
                        callback(verified, b"")

            def finish(self, manifest, phase, error_code=None):
                metadata = {
                    "type": "paste_progress",
                    "job_id": manifest.job_id,
                    "phase": phase,
                    "bytes_done": 0,
                    "bytes_total": 0,
                    "bytes_per_second": 0,
                }
                if error_code is not None:
                    metadata["error_code"] = error_code
                for callback in self.callbacks.get("paste_progress", ()):
                    callback(metadata, b"")

        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "empty.bin"
            source_path.write_bytes(b"")
            source = SourceFile.snapshot(source_path)
            jobs = [
                Manifest.create([
                    FileItem(
                        f"{name}.bin",
                        ItemType.FILE,
                        0,
                        source.modified_ns,
                        source.sha256,
                    )
                ])
                for name in ("A", "B", "C", "D")
            ]
            lane = Lane()
            executor = FifoTransferExecutor(TransferSender(lane))
            with self.assertLogs(
                "app.file_transfer.executor", level="ERROR"
            ) as logs:
                for manifest in jobs:
                    executor.submit(
                        manifest,
                        {manifest.items[0].relative_path: source},
                    )

                self.assertTrue(executor.wait_until_started(jobs[0], timeout=1))
                self.assertFalse(executor.wait_until_started(jobs[1], timeout=0.05))
                lane.finish(jobs[0], "completed")
                self.assertTrue(executor.wait_until_started(jobs[1], timeout=1))
                self.assertFalse(executor.wait_until_started(jobs[2], timeout=0.05))
                lane.finish(jobs[1], "failed", "ExplorerCopyFailed")
                self.assertTrue(executor.wait_until_started(jobs[2], timeout=1))
                self.assertFalse(executor.wait_until_started(jobs[3], timeout=0.05))
                lane.finish(jobs[2], "cancelled")
                self.assertTrue(executor.wait_until_started(jobs[3], timeout=1))
                lane.finish(jobs[3], "completed")
                self.assertTrue(executor.wait_until_idle(timeout=1))
            self.assertIn("DestinationPasteError", "\n".join(logs.output))

    def test_only_one_job_runs_and_later_jobs_preserve_fifo_order(self):
        sender = BlockingSender()
        executor = FifoTransferExecutor(sender)

        executor.submit("A", {})
        executor.submit("B", {})
        executor.submit("C", {})

        self.assertTrue(executor.wait_until_started("A", timeout=1))
        self.assertEqual(sender.started, ["A"])
        sender.release_first.set()
        self.assertTrue(executor.wait_until_idle(timeout=1))
        self.assertEqual(sender.started, ["A", "B", "C"])
        self.assertEqual(sender.finished, ["A", "B", "C"])

    def test_expected_cancellation_is_not_logged_as_failure_and_queue_continues(self):
        class CancellingSender:
            def __init__(self):
                self.started = []

            def send_job(self, manifest, sources, announce_manifest=False):
                self.started.append(manifest)
                if manifest == "cancelled":
                    raise TransferCancelled(manifest)

        sender = CancellingSender()
        executor = FifoTransferExecutor(sender)

        with self.assertNoLogs("app.file_transfer.executor", level="ERROR"):
            executor.submit("cancelled", {})
            executor.submit("next", {})
            self.assertTrue(executor.wait_until_idle(timeout=1))

        self.assertEqual(sender.started, ["cancelled", "next"])


if __name__ == "__main__":
    unittest.main()
