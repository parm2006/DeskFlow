import unittest
import threading
import time

from app.file_transfer.publisher import (
    VirtualPastePublisher, build_virtual_file_set, inject_paste_shortcut,
    release_virtual_clipboard_owner,
)


class RecordingReceiver:
    def __init__(self):
        self.reads = []
        self.consumed = []

    def read_range(self, job_id, path, offset, count):
        self.reads.append((job_id, path, offset, count))
        return b"data"[offset:offset + count]

    def record_stream_read(self, job_id, path, offset, count):
        self.consumed.append((job_id, path, offset, count))

    def record_stream_open(self, job_id, path):
        return None

    def record_stream_close(self, job_id, path):
        return None

    def wait_until_network_verified(self, job_id):
        return True


class VirtualPastePublisherTests(unittest.TestCase):
    def test_release_checks_wrapped_clipboard_interface(self):
        interface = object()
        owner = type("Owner", (), {"clipboard_interface": interface})()
        checked = []

        self.assertTrue(
            release_virtual_clipboard_owner(
                owner,
                is_current=lambda candidate: checked.append(candidate) or True,
                clear=lambda: None,
            )
        )
        self.assertEqual(checked, [interface])

    def test_release_clears_only_the_matching_current_clipboard_owner(self):
        owner = object()
        cleared = []

        self.assertFalse(
            release_virtual_clipboard_owner(
                owner,
                is_current=lambda candidate: False,
                clear=lambda: cleared.append("cleared"),
            )
        )
        self.assertEqual(cleared, [])

        self.assertTrue(
            release_virtual_clipboard_owner(
                owner,
                is_current=lambda candidate: candidate is owner,
                clear=lambda: cleared.append("cleared"),
            )
        )
        self.assertEqual(cleared, ["cleared"])

    def test_default_explorer_acceptance_deadline_is_fifteen_seconds(self):
        publisher = VirtualPastePublisher()

        self.assertEqual(publisher.explorer_start_timeout, 15.0)

    def test_successful_virtual_paste_restores_the_clipboard_it_temporarily_replaced(self):
        receiver = self.make_receiver()
        previous_owner = object()
        virtual_owner = object()
        restored = []

        def publish(
            file_set, on_performed_drop=None, on_operation_end=None,
        ):
            on_performed_drop()
            return virtual_owner

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=lambda keyboard: None,
            capture=lambda: previous_owner,
            restore=lambda owner, previous: restored.append((owner, previous)),
            keyboard_factory=object,
        )

        self.assertTrue(
            publisher._process(self.manifest("A"), receiver, object())
        )
        self.assertEqual(restored, [(virtual_owner, previous_owner)])

    def test_virtual_clipboard_is_not_published_before_network_cache_is_ready(self):
        receiver = self.make_receiver()
        receiver.wait_until_network_verified = lambda job_id: False
        published = []
        publisher = VirtualPastePublisher(
            publish=lambda *args, **kwargs: published.append("published"),
            inject=lambda keyboard: None,
            capture=lambda: None,
            restore=lambda owner, previous: None,
            keyboard_factory=object,
            explorer_start_timeout=0.01,
        )

        self.assertFalse(
            publisher._process(self.manifest("A"), receiver, object())
        )
        self.assertEqual(published, [])

    @staticmethod
    def manifest(job_id):
        return {
            "job_id": job_id,
            "items": [
                {
                    "relative_path": f"{job_id}.txt",
                    "item_type": "file",
                    "size": 4,
                    "modified_ns": 0,
                    "sha256": "0" * 64,
                }
            ],
            "total_size": 4,
            "file_count": 1,
        }

    def make_receiver(self):
        class Receiver(RecordingReceiver):
            def __init__(self):
                super().__init__()
                self.drops = []
                self.failures = []
                self.terminals = set()

            def record_performed_drop(self, job_id):
                self.drops.append(job_id)
                self.terminals.add(job_id)
                return True

            def fail_paste(self, job_id, error_code):
                self.failures.append((job_id, error_code))
                self.terminals.add(job_id)
                return True

            def is_paste_terminal(self, job_id):
                return job_id in self.terminals

        return Receiver()

    def test_worker_survives_one_failed_paste_and_processes_the_next(self):
        receiver = self.make_receiver()
        injected = []

        def publish(
            file_set, on_performed_drop=None, on_operation_end=None,
        ):
            owner = object()
            on_performed_drop()
            return owner

        def inject(keyboard):
            injected.append(len(injected))
            if len(injected) == 1:
                raise RuntimeError("first injection failed")

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=inject,
            release=lambda owner: None,
            keyboard_factory=object,
            explorer_start_timeout=0.1,
        )

        with self.assertLogs("app.file_transfer.publisher", level="ERROR") as logs:
            publisher.publish_and_paste(self.manifest("A"), receiver)
            publisher.publish_and_paste(self.manifest("B"), receiver)
            self.assertTrue(publisher.wait_until_idle(1))
        self.assertEqual(receiver.failures, [("A", "PasteInjectionFailed")])
        self.assertEqual(receiver.drops, ["A", "B"])
        self.assertEqual(len(injected), 2)
        self.assertIn("RuntimeError", "\n".join(logs.output))

    def test_accepted_job_stays_in_front_until_it_is_terminal(self):
        receiver = self.make_receiver()
        published = []
        streams = []
        operation_ends = {}

        def publish(
            file_set, on_performed_drop=None, on_operation_end=None,
        ):
            name = file_set.files[0].name
            published.append(name)
            operation_ends[name] = on_operation_end
            streams.append(file_set.files[0].open_stream())
            return object()

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=lambda keyboard: None,
            release=lambda owner: None,
            keyboard_factory=object,
        )

        publisher.publish_and_paste(self.manifest("A"), receiver)
        publisher.publish_and_paste(self.manifest("B"), receiver)

        deadline = time.monotonic() + 1
        while published != ["A.txt"] and time.monotonic() < deadline:
            threading.Event().wait(0.005)
        self.assertEqual(published, ["A.txt"])
        self.assertIsNotNone(operation_ends["A.txt"])
        operation_ends["A.txt"](0, 0)
        deadline = time.monotonic() + 1
        while published != ["A.txt", "B.txt"] and time.monotonic() < deadline:
            threading.Event().wait(0.005)
        self.assertEqual(published, ["A.txt", "B.txt"])
        self.assertIsNotNone(operation_ends["B.txt"])
        operation_ends["B.txt"](0, 0)
        self.assertTrue(publisher.wait_until_idle(1))
        self.assertEqual(published, ["A.txt", "B.txt"])

    def test_failed_async_operation_reports_safe_failure(self):
        receiver = self.make_receiver()
        streams = []

        def publish(
            file_set, on_performed_drop=None, on_operation_end=None,
        ):
            streams.append(file_set.files[0].open_stream())
            on_operation_end(-2147467259, 0)
            return object()

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=lambda keyboard: None,
            release=lambda owner: None,
            keyboard_factory=object,
        )

        self.assertTrue(
            publisher._process(self.manifest("A"), receiver, object())
        )
        self.assertEqual(receiver.failures, [("A", "ExplorerCopyFailed")])

    def test_explorer_never_consumes_times_out_and_next_job_can_run(self):
        receiver = self.make_receiver()
        publish_count = 0
        owners = []
        released = []

        def publish(
            file_set, on_performed_drop=None, on_operation_end=None,
        ):
            nonlocal publish_count
            publish_count += 1
            if publish_count == 2:
                on_performed_drop()
            owner = object()
            owners.append(owner)
            return owner

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=lambda keyboard: None,
            release=released.append,
            keyboard_factory=object,
            explorer_start_timeout=0.01,
        )

        publisher.publish_and_paste(self.manifest("A"), receiver)
        publisher.publish_and_paste(self.manifest("B"), receiver)

        self.assertTrue(publisher.wait_until_idle(1))
        self.assertEqual(receiver.failures, [("A", "ExplorerStartTimeout")])
        self.assertEqual(receiver.drops, ["B"])
        self.assertEqual(released, [owners[0]])
        self.assertEqual(publisher.retained_owner_count, 1)

    def test_cancelled_wait_does_not_block_the_next_paste(self):
        receiver = self.make_receiver()
        publish_count = 0

        def publish(
            file_set, on_performed_drop=None, on_operation_end=None,
        ):
            nonlocal publish_count
            publish_count += 1
            if publish_count == 2:
                on_performed_drop()
            return object()

        def inject(keyboard):
            if publish_count == 1:
                receiver.terminals.add("A")

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=inject,
            release=lambda owner: None,
            keyboard_factory=object,
            explorer_start_timeout=0.5,
        )

        publisher.publish_and_paste(self.manifest("A"), receiver)
        publisher.publish_and_paste(self.manifest("B"), receiver)

        self.assertTrue(publisher.wait_until_idle(0.1))
        self.assertEqual(receiver.failures, [])
        self.assertEqual(receiver.drops, ["B"])

    def test_paste_injection_releases_ctrl_when_key_press_fails(self):
        class Keyboard:
            def __init__(self):
                self.events = []

            def press(self, key):
                self.events.append(("press", key))
                if key == "v":
                    raise RuntimeError("injection failed")

            def release(self, key):
                self.events.append(("release", key))

        keyboard = Keyboard()

        with self.assertRaises(RuntimeError):
            inject_paste_shortcut(keyboard, ctrl_key="ctrl")

        self.assertEqual(keyboard.events[-1], ("release", "ctrl"))

    def test_manifest_becomes_directory_and_growing_file_streams(self):
        receiver = RecordingReceiver()
        manifest = {
            "job_id": "job-A",
            "items": [
                {"relative_path": "folder", "item_type": "directory", "size": 0, "modified_ns": 0, "sha256": None},
                {"relative_path": "folder/file.txt", "item_type": "file", "size": 4, "modified_ns": 0, "sha256": "0" * 64},
            ],
            "total_size": 4,
            "file_count": 1,
        }

        file_set = build_virtual_file_set(manifest, receiver)

        self.assertTrue(file_set.files[0].is_directory)
        stream = file_set.files[1].open_stream()
        self.assertEqual(stream.Read(4), b"data")
        self.assertEqual(receiver.reads, [("job-A", "folder/file.txt", 0, 4)])
        self.assertEqual(receiver.consumed, [("job-A", "folder/file.txt", 0, 4)])


if __name__ == "__main__":
    unittest.main()
