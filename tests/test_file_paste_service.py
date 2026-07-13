import unittest

from app.file_transfer.handshake import ManifestHandshakeQueue
from app.file_transfer.paste_service import FilePasteService


class RecordingControl:
    def __init__(self):
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return True


class RecordingReceiver:
    def __init__(self):
        self.manifests = []

    def accept_manifest(self, manifest):
        self.manifests.append(manifest)


class RecordingPublisher:
    def __init__(self):
        self.jobs = []

    def publish_and_paste(self, manifest, receiver):
        self.jobs.append(manifest["job_id"])


class RecordingSender:
    def __init__(self):
        self.jobs = []

    def send_job(self, manifest, sources, announce_manifest=True):
        self.jobs.append((manifest.job_id, tuple(sources), announce_manifest))


class ImmediateExecutor:
    def __init__(self, sender):
        self.sender = sender

    def submit(self, manifest, sources):
        self.sender.send_job(manifest, sources, announce_manifest=False)


class Manifest:
    def __init__(self, job_id):
        self.job_id = job_id

    def to_wire(self):
        return {"job_id": self.job_id, "items": [], "total_size": 0, "file_count": 0}


class FilePasteServiceTests(unittest.TestCase):
    def make_service(self, snapshots):
        control = RecordingControl()
        receiver = RecordingReceiver()
        publisher = RecordingPublisher()
        sender = RecordingSender()
        service = FilePasteService(
            control=control,
            receiver=receiver,
            publisher=publisher,
            sender=sender,
            snapshot_selection=lambda: snapshots.pop(0),
            executor=ImmediateExecutor(sender),
        )
        return service, control, receiver, publisher, sender

    def test_source_does_not_snapshot_until_manifest_request_arrives(self):
        snapshots = [(Manifest("A"), {"a.txt": object()})]
        service, control, _, _, _ = self.make_service(snapshots)

        self.assertEqual(len(snapshots), 1)
        service.on_manifest_request({"request_id": "request-1"})

        self.assertEqual(snapshots, [])
        self.assertEqual(control.messages[0]["type"], "file_manifest_response")
        self.assertEqual(control.messages[0]["request_id"], "request-1")

    def test_destination_accepts_each_response_publishes_fifo_and_acknowledges(self):
        service, control, receiver, publisher, _ = self.make_service([])
        first = service.request_paste()
        second = service.request_paste()

        service.on_manifest_response({"request_id": first.request_id, "manifest": {"job_id": "A"}})
        service.on_manifest_response({"request_id": second.request_id, "manifest": {"job_id": "B"}})

        self.assertEqual(publisher.jobs, ["A", "B"])
        self.assertEqual(receiver.manifests, [{"job_id": "A"}, {"job_id": "B"}])
        self.assertEqual(
            [message["job_id"] for message in control.messages if message["type"] == "file_manifest_ack"],
            ["A", "B"],
        )

    def test_source_starts_exact_snapshot_only_after_ack(self):
        snapshots = [(Manifest("A"), {"a.txt": object()})]
        service, _, _, _, sender = self.make_service(snapshots)
        service.on_manifest_request({"request_id": "request-1"})
        self.assertEqual(sender.jobs, [])

        service.on_manifest_ack({"job_id": "A"})

        self.assertEqual(sender.jobs, [("A", ("a.txt",), False)])


if __name__ == "__main__":
    unittest.main()
