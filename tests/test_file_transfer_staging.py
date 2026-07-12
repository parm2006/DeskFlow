import hashlib
import tempfile
import unittest
from pathlib import Path

from app.file_transfer.staging import IntegrityError, StagedFile


class StagedFileTests(unittest.TestCase):
    def test_writes_in_order_verifies_hash_and_finalizes_without_overwrite(self):
        content = b"DeskFlow file bytes"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = StagedFile(root, "job-1", "folder/report.txt", len(content), digest)

            staged.write(0, content[:8])
            staged.write(8, content[8:])
            completed = staged.finalize()

            self.assertEqual(completed.read_bytes(), content)
            self.assertFalse(staged.partial_path.exists())

            duplicate = StagedFile(root, "job-1", "folder/report.txt", len(content), digest)
            duplicate.write(0, content)
            with self.assertRaises(FileExistsError):
                duplicate.finalize()
            duplicate.abort()

    def test_rejects_out_of_order_or_oversized_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            staged = StagedFile(Path(directory), "job", "safe.bin", 4, hashlib.sha256(b"data").hexdigest())
            with self.assertRaisesRegex(ValueError, "offset"):
                staged.write(1, b"d")
            with self.assertRaisesRegex(ValueError, "declared size"):
                staged.write(0, b"extra")
            staged.abort()

    def test_hash_mismatch_never_publishes_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = StagedFile(root, "job", "safe.bin", 4, "0" * 64)
            staged.write(0, b"data")

            with self.assertRaises(IntegrityError):
                staged.finalize()

            self.assertFalse((root / "completed" / "job" / "safe.bin").exists())
            self.assertFalse(staged.partial_path.exists())


if __name__ == "__main__":
    unittest.main()
