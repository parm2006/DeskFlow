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
        elif metadata["type"] == "paste_progress":
            for callback in self.callbacks.get("paste_progress", ()):
                callback(metadata, payload)

    def emit(self, metadata, payload=b""):
        for callback in self.callbacks.get(metadata["type"], ()):
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

    def test_waits_for_destination_owned_explorer_progress_after_network_verification(self):
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

            lane = LoopbackLane(receiver)
            TransferSender(lane, controller=controller).send_job(
                manifest, {"report.txt": source}
            )

            self.assertEqual(observed[0].phase, TransferPhase.WAITING_FOR_EXPLORER)
            self.assertNotIn(TransferPhase.TRANSFERRING, [status.phase for status in observed])
            self.assertNotIn(TransferPhase.VERIFYING, [status.phase for status in observed])
            self.assertEqual(observed[-1].phase, TransferPhase.WAITING_FOR_EXPLORER)
            lane.emit({
                "type": "paste_progress", "job_id": manifest.job_id,
                "phase": "completed", "bytes_done": source.size,
                "bytes_total": source.size, "bytes_per_second": source.size,
            })
            self.assertEqual(observed[-1].phase, TransferPhase.COMPLETED)
            self.assertEqual(observed[-1].bytes_done, source.size)

    def test_rejects_impossible_or_regressing_remote_paste_progress(self):
        controller = TransferController()
        lane = type("Lane", (), {"callbacks": {}, "register_callback": lambda self, kind, cb: self.callbacks.setdefault(kind, []).append(cb)})()
        sender = TransferSender(lane, controller=controller)
        sender._paste_jobs["job"] = ("file.bin", 100)
        controller.update("job", TransferPhase.PASTING, "file.bin", 50, 100, 10)

        self.assertFalse(sender._on_paste_progress({
            "job_id": "job", "phase": "pasting", "bytes_done": 40,
            "bytes_total": 100, "bytes_per_second": 10,
        }, b""))
        self.assertFalse(sender._on_paste_progress({
            "job_id": "job", "phase": "pasting", "bytes_done": 60,
            "bytes_total": 101, "bytes_per_second": 10,
        }, b""))
        self.assertEqual(controller.status("job").bytes_done, 50)

    def test_late_network_verification_cannot_reset_active_explorer_progress(self):
        controller = TransferController()
        lane = type("Lane", (), {"callbacks": {}, "register_callback": lambda self, kind, cb: self.callbacks.setdefault(kind, []).append(cb)})()
        sender = TransferSender(lane, controller=controller)
        manifest = Manifest.create([FileItem("file.bin", ItemType.FILE, 100, 1, "0" * 64)])
        controller.update(manifest.job_id, TransferPhase.PASTING, "file.bin", 40, 100, 10)

        sender._waiting(manifest, "file.bin")

        self.assertEqual(controller.status(manifest.job_id).phase, TransferPhase.PASTING)
        self.assertEqual(controller.status(manifest.job_id).bytes_done, 40)


if __name__ == "__main__":
    unittest.main()
