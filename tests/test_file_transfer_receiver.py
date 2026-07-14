import hashlib
import tempfile
import unittest
import threading
import time
from pathlib import Path

from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.receiver import TransferAbortedError
from app.file_transfer.controller import TransferController
from app.file_transfer.status import TransferPhase


class TransferReceiverTests(unittest.TestCase):
    def test_early_last_stream_release_cancels_after_grace_period(self):
        callbacks = []

        class Timer:
            def __init__(self, delay, callback):
                callbacks.append(callback)

            def start(self):
                return None

        item = FileItem("copy.bin", ItemType.FILE, 4, 1, "0" * 64)
        manifest = Manifest.create([item])
        controller = TransferController()
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(
                Path(directory), controller=controller, timer_factory=Timer
            )
            receiver.accept_manifest(manifest.to_wire())
            receiver.record_stream_open(manifest.job_id, item.relative_path)
            receiver.record_stream_read(manifest.job_id, item.relative_path, 0, 2)
            receiver.record_stream_close(manifest.job_id, item.relative_path)
            callbacks.pop()()

        self.assertEqual(controller.status(manifest.job_id).phase, TransferPhase.CANCELLED)

    def test_stream_reopen_invalidates_pending_release_cancellation(self):
        callbacks = []

        class Timer:
            def __init__(self, delay, callback):
                callbacks.append(callback)

            def start(self):
                return None

        item = FileItem("copy.bin", ItemType.FILE, 4, 1, "0" * 64)
        manifest = Manifest.create([item])
        controller = TransferController()
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(
                Path(directory), controller=controller, timer_factory=Timer
            )
            receiver.accept_manifest(manifest.to_wire())
            receiver.record_stream_open(manifest.job_id, item.relative_path)
            receiver.record_stream_read(manifest.job_id, item.relative_path, 0, 2)
            receiver.record_stream_close(manifest.job_id, item.relative_path)
            receiver.record_stream_open(manifest.job_id, item.relative_path)
            callbacks.pop()()

        self.assertNotEqual(controller.status(manifest.job_id).phase, TransferPhase.CANCELLED)

    def test_paste_progress_updates_are_rate_limited(self):
        size = 2 * 1024 * 1024
        item = FileItem("large.bin", ItemType.FILE, size, 1, "0" * 64)
        manifest = Manifest.create([item])
        times = iter((0.0, 0.0, 0.0, 0.01, 0.01))
        controller = TransferController()
        observed = []
        controller.subscribe(observed.append)
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory), controller=controller, clock=lambda: next(times))
            receiver.accept_manifest(manifest.to_wire())
            receiver.record_stream_read(manifest.job_id, item.relative_path, 0, 1)
            receiver.record_stream_read(manifest.job_id, item.relative_path, 1, 1)

        pasting = [status for status in observed if status.phase is TransferPhase.PASTING]
        self.assertEqual(len(pasting), 1)
        self.assertEqual(pasting[0].bytes_done, 1)

    def test_stream_read_never_blocks_on_peer_progress_send(self):
        content = b"nonblocking"
        item = FileItem("safe.bin", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])

        class BlockingLane:
            def __init__(self):
                self.callbacks = {}
                self.entered = threading.Event()
                self.release = threading.Event()

            def register_callback(self, kind, callback):
                self.callbacks.setdefault(kind, []).append(callback)

            def send(self, metadata, payload=b""):
                if metadata["type"] == "paste_progress":
                    self.entered.set()
                    self.release.wait(1)

        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))
            lane = BlockingLane()
            receiver.attach(lane)
            receiver.accept_manifest(manifest.to_wire())
            started = time.monotonic()
            receiver.record_stream_read(manifest.job_id, item.relative_path, 0, 1)
            elapsed = time.monotonic() - started
            self.assertTrue(lane.entered.wait(1))
            lane.release.set()

        self.assertLess(elapsed, 0.05)

    def test_network_receipt_does_not_drive_user_facing_progress(self):
        content = b"actual bytes"
        item = FileItem("speed.bin", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])
        controller = TransferController()
        times = iter((10.0, 12.0, 14.0))
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory), controller=controller, clock=lambda: next(times))
            receiver.accept_manifest(manifest.to_wire())
            receiver.accept_chunk({
                "job_id": manifest.job_id, "relative_path": "speed.bin", "offset": 0,
                "compressed": False, "original_size": len(content),
            }, content)

            status = controller.status(manifest.job_id)
            self.assertEqual(status.phase, TransferPhase.WAITING_FOR_EXPLORER)
            self.assertEqual(status.bytes_done, 0)
            self.assertEqual(status.bytes_per_second, 0)
            receiver.cancel_job(manifest.job_id)


    def test_reports_received_bytes_and_verified_completion(self):
        content = b"verified progress"
        item = FileItem("safe.txt", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])
        controller = TransferController()
        observed = []
        controller.subscribe(observed.append)
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory), controller=controller)
            receiver.accept_manifest(manifest.to_wire())
            receiver.accept_chunk({
                "job_id": manifest.job_id, "relative_path": "safe.txt", "offset": 0,
                "compressed": False, "original_size": len(content),
            }, content)
            receiver.complete_file(manifest.job_id, "safe.txt")
            receiver.complete_job(manifest.job_id)

        self.assertEqual(observed[0].phase, TransferPhase.WAITING_FOR_EXPLORER)
        self.assertNotIn(TransferPhase.TRANSFERRING, [status.phase for status in observed])
        self.assertNotIn(TransferPhase.VERIFYING, [status.phase for status in observed])
        self.assertEqual(observed[-1].phase, TransferPhase.WAITING_FOR_EXPLORER)

    def test_explorer_reads_drive_paste_progress_and_fallback_completion(self):
        content = b"explorer consumed bytes"
        item = FileItem("copy.bin", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])
        controller = TransferController()
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory), controller=controller)
            receiver.accept_manifest(manifest.to_wire())
            receiver.accept_chunk({
                "job_id": manifest.job_id, "relative_path": item.relative_path, "offset": 0,
                "compressed": False, "original_size": len(content),
            }, content)
            receiver.complete_file(manifest.job_id, item.relative_path)
            receiver.complete_job(manifest.job_id)
            receiver.record_stream_read(manifest.job_id, item.relative_path, 0, 8)
            self.assertEqual(controller.status(manifest.job_id).phase, TransferPhase.PASTING)
            self.assertEqual(controller.status(manifest.job_id).bytes_done, 8)
            receiver.record_stream_read(manifest.job_id, item.relative_path, 8, len(content) - 8)

        self.assertEqual(controller.status(manifest.job_id).phase, TransferPhase.COMPLETED)
        self.assertEqual(controller.status(manifest.job_id).bytes_done, len(content))

    def test_performed_drop_with_incomplete_coverage_cancels_paste(self):
        item = FileItem("copy.bin", ItemType.FILE, 4, 1, "0" * 64)
        manifest = Manifest.create([item])
        controller = TransferController()
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory), controller=controller)
            receiver.accept_manifest(manifest.to_wire())

            receiver.record_performed_drop(manifest.job_id)

        self.assertEqual(controller.status(manifest.job_id).phase, TransferPhase.CANCELLED)

    def test_manifest_chunks_and_completion_publish_verified_file(self):
        content = b"DeskFlow received bytes"
        item = FileItem("folder/report.txt", ItemType.FILE, len(content), 123, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))

            receiver.accept_manifest(manifest.to_wire())
            receiver.accept_chunk(
                {
                    "job_id": manifest.job_id,
                    "relative_path": item.relative_path,
                    "offset": 0,
                    "compressed": False,
                    "original_size": len(content),
                },
                content,
            )
            completed = receiver.complete_file(manifest.job_id, item.relative_path)

            self.assertEqual(completed.read_available(0, len(content)), content)

    def test_rejects_chunks_for_unknown_job_or_path(self):
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))
            metadata = {
                "job_id": "unknown",
                "relative_path": "safe.txt",
                "offset": 0,
                "compressed": False,
                "original_size": 1,
            }
            with self.assertRaises(KeyError):
                receiver.accept_chunk(metadata, b"x")

    def test_reader_waits_for_requested_bytes_while_transfer_grows(self):
        content = b"streamed"
        item = FileItem("stream.bin", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))
            receiver.accept_manifest(manifest.to_wire())
            result = []
            reader = threading.Thread(
                target=lambda: result.append(receiver.read_range(manifest.job_id, item.relative_path, 0, 4))
            )
            reader.start()
            time.sleep(0.02)
            self.assertTrue(reader.is_alive())

            receiver.accept_chunk(
                {
                    "job_id": manifest.job_id,
                    "relative_path": item.relative_path,
                    "offset": 0,
                    "compressed": False,
                    "original_size": len(content),
                },
                content,
            )
            reader.join(1)

            self.assertEqual(result, [b"stre"])
            receiver.cancel_job(manifest.job_id)

    def test_cancel_wakes_blocked_reader_with_error(self):
        item = FileItem("blocked.bin", ItemType.FILE, 4, 1, hashlib.sha256(b"data").hexdigest())
        manifest = Manifest.create([item])
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))
            receiver.accept_manifest(manifest.to_wire())
            errors = []

            def read():
                try:
                    receiver.read_range(manifest.job_id, item.relative_path, 0, 4)
                except Exception as error:
                    errors.append(error)

            reader = threading.Thread(target=read)
            reader.start()
            time.sleep(0.02)
            receiver.cancel_job(manifest.job_id)
            reader.join(1)

            self.assertFalse(reader.is_alive())
            self.assertIsInstance(errors[0], TransferAbortedError)

    def test_cancel_prevents_reads_from_already_completed_file(self):
        content = b"completed before cancel"
        item = FileItem("done.bin", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        manifest = Manifest.create([item])
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))
            receiver.accept_manifest(manifest.to_wire())
            receiver.accept_chunk({
                "job_id": manifest.job_id, "relative_path": item.relative_path,
                "offset": 0, "compressed": False, "original_size": len(content),
            }, content)
            receiver.complete_file(manifest.job_id, item.relative_path)
            receiver.cancel_job(manifest.job_id)

            with self.assertRaises(TransferAbortedError):
                receiver.read_range(manifest.job_id, item.relative_path, 0, len(content))

    def test_same_relative_path_completes_independently_in_two_jobs(self):
        content = b"same file"
        item = FileItem("same.txt", ItemType.FILE, len(content), 1, hashlib.sha256(content).hexdigest())
        with tempfile.TemporaryDirectory() as directory:
            receiver = TransferReceiver(Path(directory))
            completed = []
            for _ in range(2):
                manifest = Manifest.create([item])
                receiver.accept_manifest(manifest.to_wire())
                receiver.accept_chunk(
                    {
                        "job_id": manifest.job_id,
                        "relative_path": "same.txt",
                        "offset": 0,
                        "compressed": False,
                        "original_size": len(content),
                    },
                    content,
                )
                completed.append(receiver.complete_file(manifest.job_id, "same.txt"))

            self.assertNotEqual(completed[0], completed[1])
            self.assertEqual(
                [staged.read_available(0, len(content)) for staged in completed],
                [content, content],
            )


if __name__ == "__main__":
    unittest.main()
