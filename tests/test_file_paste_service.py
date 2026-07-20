import inspect
import threading
import time
import unittest

from app.file_transfer.handshake import RequestState
from app.file_transfer.paste_service import FilePasteService
from app.file_transfer.controller import TransferController
from app.file_transfer.status import TransferPhase


JOB_A = "a" * 32
JOB_B = "b" * 32
VALID_REQUEST = "1" * 32


class RecordingControl:
    def __init__(self):
        self.messages = []
        self.callbacks = {}

    def send_message(self, message):
        self.messages.append(message)
        return True

    def register_callback(self, kind, callback):
        self.callbacks.setdefault(kind, []).append(callback)

    def disconnect(self):
        for callback in tuple(self.callbacks.get("disconnected", ())):
            callback({})


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
        self.total_size = 0
        self.file_count = 0

    def to_wire(self):
        return {
            "job_id": self.job_id,
            "items": [],
            "total_size": self.total_size,
            "file_count": self.file_count,
        }


class FilePasteServiceTests(unittest.TestCase):
    @staticmethod
    def wait_for(predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return bool(predicate())

    def test_slow_snapshot_keeps_callbacks_responsive_and_completes_after_one_second(self):
        snapshot_started = threading.Event()
        release_snapshot = threading.Event()
        callback_returned = threading.Event()
        results = []
        snapshot_calls = []

        def snapshot_selection():
            snapshot_calls.append(True)
            snapshot_started.set()
            release_snapshot.wait()
            return Manifest(JOB_A), {"a.txt": object()}

        source, source_control, _, _, _ = self.make_service(
            snapshot_selection=snapshot_selection,
        )
        destination, _, _, publisher, _ = self.make_service([])
        pending = destination.request_paste()

        def invoke_callback():
            results.append(
                source.on_manifest_request({"request_id": pending.request_id})
            )
            callback_returned.set()

        callback = threading.Thread(target=invoke_callback)
        callback.start()
        try:
            self.assertTrue(snapshot_started.wait(0.5))
            self.assertTrue(
                callback_returned.wait(0.5),
                "manifest callback blocked on selection traversal and hashing",
            )
            self.assertEqual(results, [True])
            self.assertFalse(
                source.on_manifest_request({"request_id": VALID_REQUEST})
            )
            self.assertEqual(snapshot_calls, [True])
            busy = next(
                message for message in source_control.messages
                if message["type"] == "file_manifest_failed"
            )
            self.assertEqual(busy["request_id"], VALID_REQUEST)
            self.assertEqual(busy["error"], "ManifestLimitError")
            time.sleep(1.05)
        finally:
            release_snapshot.set()
            callback.join(1.0)

        self.assertTrue(
            self.wait_for(
                lambda: any(
                    message["type"] == "file_manifest_response"
                    for message in source_control.messages
                )
            )
        )
        response = next(
            message for message in source_control.messages
            if message["type"] == "file_manifest_response"
        )
        self.assertTrue(destination.on_manifest_response(response))
        self.assertEqual(publisher.jobs, [JOB_A])

    def test_manifest_handshake_surfaces_preparing_then_failure_status(self):
        controller = TransferController()
        service, _, _, _, _ = self.make_service(
            [], controller=controller
        )

        pending = service.request_paste()
        preparing = controller.status(pending.request_id)
        self.assertEqual(preparing.phase, TransferPhase.PREPARING)
        self.assertEqual(preparing.label, "Files")

        service.on_manifest_failed({
            "request_id": pending.request_id,
            "error": "ManifestLimitError",
        })

        failed = controller.status(pending.request_id)
        self.assertEqual(failed.phase, TransferPhase.FAILED)
        self.assertEqual(failed.error_code, "ManifestLimitError")

    def test_accepted_manifest_replaces_request_scoped_preparing_status(self):
        controller = TransferController()
        service, _, receiver, publisher, _ = self.make_service(
            [], controller=controller
        )
        pending = service.request_paste()

        self.assertTrue(service.on_manifest_response({
            "request_id": pending.request_id,
            "manifest": {"job_id": JOB_A},
        }))

        self.assertIsNone(controller.status(pending.request_id))
        self.assertEqual(receiver.manifests, [{"job_id": JOB_A}])
        self.assertEqual(publisher.jobs, [JOB_A])

    def test_rejected_manifest_turns_preparing_status_into_safe_failure(self):
        class RejectingReceiver(RecordingReceiver):
            def accept_manifest(self, manifest):
                raise ValueError("private invalid manifest detail")

        controller = TransferController()
        control = RecordingControl()
        publisher = RecordingPublisher()
        sender = RecordingSender()
        service = FilePasteService(
            control=control,
            receiver=RejectingReceiver(),
            publisher=publisher,
            sender=sender,
            snapshot_selection=lambda: None,
            executor=ImmediateExecutor(sender),
            controller=controller,
        )
        pending = service.request_paste()

        with self.assertLogs(
            "app.file_transfer.paste_service", level="ERROR"
        ) as logs:
            self.assertFalse(service.on_manifest_response({
                "request_id": pending.request_id,
                "manifest": {"job_id": JOB_A},
            }))

        status = controller.status(pending.request_id)
        self.assertEqual(status.phase, TransferPhase.FAILED)
        self.assertEqual(status.error_code, "ManifestPreparationFailed")
        self.assertNotIn("private invalid manifest detail", "\n".join(logs.output))

    def test_disconnect_terminalizes_request_scoped_preparing_status(self):
        controller = TransferController()
        service, control, _, _, _ = self.make_service(
            [], controller=controller
        )
        pending = service.request_paste()

        control.disconnect()

        self.assertEqual(
            controller.status(pending.request_id).phase,
            TransferPhase.CANCELLED,
        )

    def test_destination_acknowledges_before_async_paste_can_report_failure(self):
        events = []

        class Control(RecordingControl):
            def send_message(self, message):
                events.append(("send", message["type"]))
                return super().send_message(message)

        class Publisher(RecordingPublisher):
            def publish_and_paste(self, manifest, receiver):
                events.append(("publish", manifest["job_id"]))
                return super().publish_and_paste(manifest, receiver)

        control = Control()
        receiver = RecordingReceiver()
        publisher = Publisher()
        sender = RecordingSender()
        service = FilePasteService(
            control=control,
            receiver=receiver,
            publisher=publisher,
            sender=sender,
            snapshot_selection=lambda: None,
            executor=ImmediateExecutor(sender),
        )
        pending = service.request_paste()

        service.on_manifest_response({
            "request_id": pending.request_id,
            "manifest": {"job_id": JOB_A},
        })

        self.assertEqual(
            events,
            [("send", "file_manifest_request"), ("send", "file_manifest_ack"), ("publish", JOB_A)],
        )

    def make_service(self, snapshots=None, snapshot_selection=None, **options):
        control = RecordingControl()
        receiver = RecordingReceiver()
        publisher = RecordingPublisher()
        sender = RecordingSender()
        if snapshot_selection is None:
            snapshot_selection = lambda: snapshots.pop(0)
        service = FilePasteService(
            control=control,
            receiver=receiver,
            publisher=publisher,
            sender=sender,
            snapshot_selection=snapshot_selection,
            executor=ImmediateExecutor(sender),
            **options,
        )
        return service, control, receiver, publisher, sender

    def test_source_does_not_snapshot_until_manifest_request_arrives(self):
        snapshots = [(Manifest(JOB_A), {"a.txt": object()})]
        service, control, _, _, _ = self.make_service(snapshots)

        self.assertEqual(len(snapshots), 1)
        service.on_manifest_request({"request_id": VALID_REQUEST})

        self.assertTrue(self.wait_for(lambda: snapshots == []))
        self.assertTrue(self.wait_for(lambda: bool(control.messages)))
        self.assertEqual(control.messages[0]["type"], "file_manifest_response")
        self.assertEqual(control.messages[0]["request_id"], VALID_REQUEST)

    def test_invalid_request_id_is_rejected_before_snapshotting(self):
        snapshots = [(Manifest(JOB_A), {"a.txt": object()})]
        service, control, _, _, _ = self.make_service(snapshots)

        self.assertFalse(service.on_manifest_request({"request_id": "not-valid"}))

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(control.messages, [])

    def test_outgoing_snapshots_are_bounded_before_more_hashing_occurs(self):
        snapshots = [
            (Manifest(f"{number:032x}"), {f"{number}.txt": object()})
            for number in range(9)
        ]
        service, control, _, _, _ = self.make_service(snapshots)

        for number in range(8):
            self.assertTrue(
                service.on_manifest_request({"request_id": f"{number + 1:032x}"})
            )
            self.assertTrue(
                self.wait_for(
                    lambda: sum(
                        message["type"] == "file_manifest_response"
                        for message in control.messages
                    ) == number + 1
                )
            )
        self.assertFalse(service.on_manifest_request({"request_id": "f" * 32}))

        self.assertEqual(len(service._outgoing), 8)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(control.messages[-1]["type"], "file_manifest_failed")

    def test_unacknowledged_snapshot_expires_and_releases_sources(self):
        snapshots = [(Manifest(JOB_A), {"a.txt": object()})]
        service, _, _, _, _ = self.make_service(snapshots)
        service._outgoing_timeout = 0.02
        service.on_manifest_request({"request_id": VALID_REQUEST})

        self.assertTrue(self.wait_for(lambda: bool(service._outgoing)))
        deadline = time.monotonic() + 1.0
        while service._outgoing and time.monotonic() < deadline:
            time.sleep(0.005)

        self.assertEqual(service._outgoing, {})

    def test_destination_accepts_each_response_publishes_fifo_and_acknowledges(self):
        service, control, receiver, publisher, _ = self.make_service([])
        first = service.request_paste()
        second = service.request_paste()

        service.on_manifest_response({"request_id": first.request_id, "manifest": {"job_id": JOB_A}})
        service.on_manifest_response({"request_id": second.request_id, "manifest": {"job_id": JOB_B}})

        self.assertEqual(publisher.jobs, [JOB_A, JOB_B])
        self.assertEqual(receiver.manifests, [{"job_id": JOB_A}, {"job_id": JOB_B}])
        self.assertEqual(
            [message["job_id"] for message in control.messages if message["type"] == "file_manifest_ack"],
            [JOB_A, JOB_B],
        )

    def test_source_starts_exact_snapshot_only_after_ack(self):
        snapshots = [(Manifest(JOB_A), {"a.txt": object()})]
        service, _, _, _, sender = self.make_service(snapshots)
        service.on_manifest_request({"request_id": VALID_REQUEST})
        self.assertTrue(self.wait_for(lambda: JOB_A in service._outgoing))
        self.assertEqual(sender.jobs, [])

        service.on_manifest_ack({"job_id": JOB_A})

        self.assertEqual(sender.jobs, [(JOB_A, ("a.txt",), False)])

    def test_worker_exception_reports_failure_and_releases_preparation_slot(self):
        attempts = []

        def snapshot_selection():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("snapshot failed")
            return Manifest(JOB_A), {"a.txt": object()}

        service, control, _, _, _ = self.make_service(
            snapshot_selection=snapshot_selection,
        )

        with self.assertLogs(
            "app.file_transfer.paste_service", level="INFO"
        ) as captured:
            self.assertTrue(
                service.on_manifest_request({"request_id": VALID_REQUEST})
            )
            self.assertTrue(
                self.wait_for(
                    lambda: control.messages
                    and control.messages[-1]["type"]
                    == "file_manifest_failed"
                    and service._preparation is None
                )
            )
        failure_log = "\n".join(captured.output)
        self.assertEqual(control.messages[-1]["error"], "RuntimeError")
        self.assertIn("error=RuntimeError", failure_log)
        self.assertNotIn("snapshot failed", failure_log)

        self.assertTrue(
            service.on_manifest_request({"request_id": "2" * 32})
        )
        self.assertTrue(
            self.wait_for(
                lambda: any(
                    message["type"] == "file_manifest_response"
                    and message["request_id"] == "2" * 32
                    for message in control.messages
                )
            )
        )

    def test_preparation_logs_safe_aggregate_metadata_without_source_paths(self):
        manifest = Manifest(JOB_A)
        manifest.file_count = 2
        manifest.total_size = 123
        private_source = "private/folder/secret.txt"
        service, control, _, _, _ = self.make_service(
            snapshot_selection=lambda: (
                manifest,
                {private_source: object()},
            ),
        )

        with self.assertLogs(
            "app.file_transfer.paste_service", level="INFO"
        ) as captured:
            self.assertTrue(
                service.on_manifest_request({"request_id": VALID_REQUEST})
            )
            self.assertTrue(
                self.wait_for(
                    lambda: any(
                        message["type"] == "file_manifest_response"
                        for message in control.messages
                    )
                )
            )

        output = "\n".join(captured.output)
        self.assertIn(f"request_id={VALID_REQUEST}", output)
        self.assertIn(f"job_id={JOB_A}", output)
        self.assertIn("file_count=2 total_bytes=123", output)
        self.assertNotIn(private_source, output)

    def test_preparation_timeout_clears_request_and_rejects_late_worker_result(self):
        self.assertIn(
            "preparation_timeout",
            inspect.signature(FilePasteService).parameters,
            "preparation deadline is not configurable",
        )
        snapshot_started = threading.Event()
        release_snapshot = threading.Event()

        def snapshot_selection():
            snapshot_started.set()
            release_snapshot.wait()
            return Manifest(JOB_A), {"a.txt": object()}

        service, control, _, _, _ = self.make_service(
            snapshot_selection=snapshot_selection,
            preparation_timeout=0.02,
        )

        self.assertTrue(service.on_manifest_request({"request_id": VALID_REQUEST}))
        try:
            self.assertTrue(snapshot_started.wait(0.5))
            self.assertTrue(
                self.wait_for(
                    lambda: any(
                        message["type"] == "file_manifest_failed"
                        and message.get("error")
                        == "ManifestPreparationTimeout"
                        for message in control.messages
                    )
                )
            )
            self.assertIsNotNone(service._preparation)
            self.assertIsNone(service._preparation["request_id"])
            self.assertFalse(
                service.on_manifest_request({"request_id": "2" * 32})
            )
        finally:
            release_snapshot.set()
        self.assertTrue(
            self.wait_for(
                lambda: service._preparation is None
            )
        )
        self.assertFalse(
            any(
                message["type"] == "file_manifest_response"
                for message in control.messages
            )
        )
        self.assertEqual(service._outgoing, {})

    def test_disconnect_releases_handshakes_and_retained_snapshots(self):
        snapshots = [(Manifest(JOB_A), {"a.txt": object()})]
        service, control, receiver, publisher, _ = self.make_service(snapshots)
        incoming = service.request_paste()
        self.assertTrue(service.on_manifest_request({"request_id": VALID_REQUEST}))
        self.assertTrue(self.wait_for(lambda: JOB_A in service._outgoing))

        control.disconnect()

        self.assertEqual(incoming.state, RequestState.CANCELLED)
        self.assertEqual(service._outgoing, {})
        self.assertEqual(service._outgoing_timers, {})
        self.assertFalse(service.on_manifest_ack({"job_id": JOB_A}))
        self.assertFalse(
            service.on_manifest_response({
                "request_id": incoming.request_id,
                "manifest": {"job_id": JOB_B},
            })
        )
        self.assertEqual(receiver.manifests, [])
        self.assertEqual(publisher.jobs, [])

    def test_disconnect_drops_result_from_worker_that_finishes_late(self):
        snapshot_started = threading.Event()
        release_snapshot = threading.Event()

        def snapshot_selection():
            snapshot_started.set()
            release_snapshot.wait()
            return Manifest(JOB_A), {"a.txt": object()}

        service, control, _, _, _ = self.make_service(
            snapshot_selection=snapshot_selection,
        )

        self.assertTrue(service.on_manifest_request({"request_id": VALID_REQUEST}))
        try:
            self.assertTrue(snapshot_started.wait(0.5))
            control.disconnect()
            self.assertIsNotNone(service._preparation)
            self.assertIsNone(service._preparation["request_id"])
            self.assertFalse(
                service.on_manifest_request({"request_id": "2" * 32})
            )
        finally:
            release_snapshot.set()

        self.assertTrue(
            self.wait_for(
                lambda: service._preparation is None
            )
        )
        self.assertEqual(service._outgoing, {})
        self.assertFalse(
            any(
                message["type"] == "file_manifest_response"
                for message in control.messages
            )
        )


if __name__ == "__main__":
    unittest.main()
