import unittest

from app.file_transfer.publisher import (
    VirtualPastePublisher, build_virtual_file_set, inject_paste_shortcut,
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


class VirtualPastePublisherTests(unittest.TestCase):
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
                return True

            def fail_paste(self, job_id, error_code):
                self.failures.append((job_id, error_code))
                return True

            def is_paste_terminal(self, job_id):
                return job_id in self.terminals

        return Receiver()

    def test_worker_survives_one_failed_paste_and_processes_the_next(self):
        receiver = self.make_receiver()
        injected = []

        def publish(file_set, on_performed_drop=None):
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

    def test_explorer_never_consumes_times_out_and_next_job_can_run(self):
        receiver = self.make_receiver()
        publish_count = 0

        def publish(file_set, on_performed_drop=None):
            nonlocal publish_count
            publish_count += 1
            if publish_count == 2:
                on_performed_drop()
            return object()

        publisher = VirtualPastePublisher(
            publish=publish,
            inject=lambda keyboard: None,
            keyboard_factory=object,
            explorer_start_timeout=0.01,
        )

        publisher.publish_and_paste(self.manifest("A"), receiver)
        publisher.publish_and_paste(self.manifest("B"), receiver)

        self.assertTrue(publisher.wait_until_idle(1))
        self.assertEqual(receiver.failures, [("A", "ExplorerStartTimeout")])
        self.assertEqual(receiver.drops, ["B"])
        self.assertEqual(publisher.retained_owner_count, 1)

    def test_cancelled_wait_does_not_block_the_next_paste(self):
        receiver = self.make_receiver()
        publish_count = 0

        def publish(file_set, on_performed_drop=None):
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
