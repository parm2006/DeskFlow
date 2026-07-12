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
    def test_reports_speed_from_actual_received_bytes(self):
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

            self.assertEqual(controller.status(manifest.job_id).bytes_per_second, len(content) / 2)
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

        self.assertEqual(observed[0].phase, TransferPhase.PREPARING)
        self.assertIn(TransferPhase.TRANSFERRING, [status.phase for status in observed])
        self.assertIn(TransferPhase.VERIFYING, [status.phase for status in observed])
        self.assertEqual(observed[-1].phase, TransferPhase.COMPLETED)

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

            self.assertEqual(completed.read_bytes(), content)

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
            self.assertEqual([path.read_bytes() for path in completed], [content, content])


if __name__ == "__main__":
    unittest.main()
