import tempfile
import unittest
from pathlib import Path

from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.sender import TransferSender
from app.file_transfer.source import SourceFile


class LoopbackLane:
    def __init__(self, receiver):
        self.receiver = receiver

    def send(self, metadata, payload=b""):
        if metadata["type"] == "manifest":
            self.receiver.accept_manifest(metadata["manifest"])
        elif metadata["type"] == "chunk":
            self.receiver.accept_chunk(metadata, payload)
        elif metadata["type"] == "file_complete":
            self.receiver.complete_file(metadata["job_id"], metadata["relative_path"])


class TransferSenderTests(unittest.TestCase):
    def test_sends_manifest_and_bounded_chunks_that_receiver_verifies(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as receive_directory:
            source_path = Path(source_directory) / "report.txt"
            source_path.write_bytes(b"DeskFlow" * 200_000)
            source = SourceFile.snapshot(source_path)
            item = FileItem("report.txt", ItemType.FILE, source.size, source.modified_ns, source.sha256)
            manifest = Manifest.create([item])
            receiver = TransferReceiver(Path(receive_directory))

            TransferSender(LoopbackLane(receiver)).send_job(manifest, {"report.txt": source})

            completed = Path(receive_directory) / "completed" / "report.txt"
            self.assertEqual(completed.read_bytes(), source_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
