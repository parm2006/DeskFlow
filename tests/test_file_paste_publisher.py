import unittest

from app.file_transfer.publisher import build_virtual_file_set, inject_paste_shortcut


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
