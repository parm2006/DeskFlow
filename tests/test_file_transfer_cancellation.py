import hashlib
import tempfile
import unittest
import threading
from unittest.mock import patch
from pathlib import Path

from app.file_transfer.cancellation import TransferCancellation
from app.file_transfer.controller import TransferController
from app.file_transfer.models import FileItem, ItemType, Manifest
from app.file_transfer.receiver import TransferReceiver
from app.file_transfer.status import TransferPhase

JOB_ONE = "1" * 32
JOB_TWO = "2" * 32
CANCEL_ONE = "c" * 32


class Lane:
    def __init__(self):
        self.callbacks = {}
        self.sent = []

    def register_callback(self, name, callback):
        self.callbacks.setdefault(name, []).append(callback)

    def send(self, metadata, payload=b""):
        self.sent.append(metadata)

    def emit(self, metadata):
        for callback in self.callbacks.get(metadata["type"], ()):
            callback(metadata, b"")


class CancellationTests(unittest.TestCase):
    def test_invalid_remote_identifiers_are_not_retained_or_acknowledged(self):
        with tempfile.TemporaryDirectory() as directory:
            lane, controller, receiver, protocol = self._active(Path(directory))
            before = len(lane.sent)

            lane.emit({
                "type": "cancel_job",
                "job_id": "not-a-job-id",
                "cancellation_id": "x" * 32,
            })
            lane.emit({
                "type": "cancel_job",
                "job_id": JOB_ONE,
                "cancellation_id": "not-a-cancellation-id",
            })

            self.assertEqual(len(lane.sent), before)
            self.assertEqual(protocol._handled, {})
            self.assertNotIn("not-a-job-id", receiver._terminal_jobs)

    def test_chunk_decoding_race_cannot_recreate_staging_after_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            lane, controller, receiver, protocol = self._active(Path(directory))
            decoding = threading.Event()
            release = threading.Event()
            results = []

            def delayed_decode(payload, compressed, original_size):
                decoding.set()
                release.wait(1)
                return payload

            metadata = {
                "job_id": JOB_ONE, "relative_path": "x", "offset": 0,
                "compressed": False, "original_size": 1,
            }
            with patch("app.file_transfer.receiver.decode_chunk", delayed_decode):
                worker = threading.Thread(
                    target=lambda: results.append(
                        receiver.accept_chunk(metadata, b"x")
                    )
                )
                worker.start()
                self.assertTrue(decoding.wait(1))
                protocol.request(JOB_ONE)
                release.set()
                worker.join(1)

            self.assertEqual(results, [False])
            self.assertNotIn(JOB_ONE, receiver._jobs)
            self.assertEqual(list(Path(directory).rglob("*.partial")), [])

    def _active(self, root, job_id=JOB_ONE):
        lane = Lane()
        controller = TransferController()
        receiver = TransferReceiver(root, controller=controller)
        receiver.attach(lane)
        item = FileItem("x", ItemType.FILE, 1, 0, hashlib.sha256(b"x").hexdigest())
        manifest = Manifest(job_id, (item,), 1, 1)
        receiver.accept_manifest(manifest.to_wire())
        controller.update(job_id, TransferPhase.TRANSFERRING, "x", 0, 1)
        protocol = TransferCancellation(lane, controller, receiver)
        return lane, controller, receiver, protocol

    def test_local_cancel_has_one_operation_and_matching_ack(self):
        with tempfile.TemporaryDirectory() as directory:
            lane, controller, receiver, protocol = self._active(Path(directory))
            self.assertTrue(protocol.request(JOB_ONE))
            request = lane.sent[-1]
            self.assertEqual(request["type"], "cancel_job")
            lane.emit({
                "type": "cancel_ack", "job_id": JOB_ONE,
                "cancellation_id": request["cancellation_id"],
            })
            self.assertEqual(controller.status(JOB_ONE).phase, TransferPhase.CANCELLED)
            self.assertFalse(protocol.request(JOB_ONE))

    def test_remote_duplicates_ack_but_apply_once_and_late_frames_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            lane, controller, receiver, protocol = self._active(Path(directory))
            cancel = {"type": "cancel_job", "job_id": JOB_ONE, "cancellation_id": CANCEL_ONE}
            lane.emit(cancel)
            lane.emit(cancel)
            self.assertEqual([m["type"] for m in lane.sent[-2:]], ["cancel_ack", "cancel_ack"])
            self.assertEqual(controller.status(JOB_ONE).phase, TransferPhase.CANCELLED)
            self.assertFalse(receiver.accept_chunk({
                "job_id": JOB_ONE, "relative_path": "x", "offset": 0,
                "compressed": False, "original_size": 1,
            }, b"x"))
            self.assertFalse(receiver.complete_file(JOB_ONE, "x"))
            self.assertFalse(receiver.complete_job(JOB_ONE))

    def test_cancelled_job_does_not_poison_next_job(self):
        with tempfile.TemporaryDirectory() as directory:
            lane, controller, receiver, protocol = self._active(Path(directory), JOB_ONE)
            protocol.request(JOB_ONE)
            item = FileItem("x", ItemType.FILE, 1, 0, hashlib.sha256(b"x").hexdigest())
            next_manifest = Manifest(JOB_TWO, (item,), 1, 1)
            self.assertIsNotNone(receiver.accept_manifest(next_manifest.to_wire()))
            self.assertTrue(receiver.accept_chunk({
                "job_id": JOB_TWO, "relative_path": "x", "offset": 0,
                "compressed": False, "original_size": 1,
            }, b"x"))
            receiver.complete_file(JOB_TWO, "x")
            receiver.complete_job(JOB_TWO)


if __name__ == "__main__":
    unittest.main()
