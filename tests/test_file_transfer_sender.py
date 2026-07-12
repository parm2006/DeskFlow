import tempfile
import unittest
from pathlib import Path

from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.sender import TransferSender
from app.file_transfer.source import SourceFile
from app.file_transfer.controller import TransferController
from app.file_transfer.status import TransferPhase


class LoopbackLane:
    def __init__(self, receiver):
        self.receiver = receiver
        self.callbacks = {}
        receiver.attach(self)

    def register_callback(self, event_type, callback):
        self.callbacks.setdefault(event_type, []).append(callback)

    def send(self, metadata, payload=b""):
        if metadata["type"] == "manifest":
            self.receiver.accept_manifest(metadata["manifest"])
        elif metadata["type"] == "chunk":
            self.receiver.accept_chunk(metadata, payload)
        elif metadata["type"] == "file_complete":
            self.receiver.complete_file(metadata["job_id"], metadata["relative_path"])
        elif metadata["type"] == "job_complete":
            self.receiver.complete_job(metadata["job_id"])
        elif metadata["type"] == "job_verified":
            for callback in self.callbacks.get("job_verified", ()):
                callback(metadata, payload)


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

            completed = Path(receive_directory) / "completed" / manifest.job_id / "report.txt"
            self.assertEqual(completed.read_bytes(), source_path.read_bytes())

    def test_reports_preparing_transfer_progress_and_completion(self):
        with tempfile.TemporaryDirectory() as source_directory, tempfile.TemporaryDirectory() as receive_directory:
            source_path = Path(source_directory) / "report.txt"
            source_path.write_bytes(b"progress bytes")
            source = SourceFile.snapshot(source_path)
            manifest = Manifest.create([
                FileItem("report.txt", ItemType.FILE, source.size, source.modified_ns, source.sha256)
            ])
            controller = TransferController()
            observed = []
            controller.subscribe(observed.append)
            receiver = TransferReceiver(Path(receive_directory))

            TransferSender(LoopbackLane(receiver), controller=controller).send_job(
                manifest, {"report.txt": source}
            )

            self.assertEqual(observed[0].phase, TransferPhase.PREPARING)
            self.assertIn(TransferPhase.TRANSFERRING, [status.phase for status in observed])
            self.assertIn(TransferPhase.VERIFYING, [status.phase for status in observed])
            self.assertEqual(observed[-1].phase, TransferPhase.COMPLETED)
            self.assertEqual(observed[-1].bytes_done, source.size)


if __name__ == "__main__":
    unittest.main()
