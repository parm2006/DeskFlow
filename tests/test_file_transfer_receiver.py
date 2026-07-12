import hashlib
import tempfile
import unittest
import threading
import time
from pathlib import Path

from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.receiver import TransferReceiver


class TransferReceiverTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
