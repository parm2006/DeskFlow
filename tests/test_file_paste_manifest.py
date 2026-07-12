import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.clipboard_handler import ClipboardHandler
from app.file_transfer.selection import snapshot_selection


class FileManifestTests(unittest.TestCase):
    def test_clipboard_paths_are_read_only_when_manifest_is_requested(self):
        handler = ClipboardHandler(lambda snapshot: None)
        paths = (r"C:\one.txt", r"C:\two.txt")
        with patch("app.clipboard_handler.win32clipboard.OpenClipboard"), patch(
            "app.clipboard_handler.win32clipboard.CloseClipboard"
        ), patch(
            "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable", return_value=True
        ), patch(
            "app.clipboard_handler.win32clipboard.GetClipboardData", return_value=paths
        ) as get_data:
            self.assertEqual(handler.read_file_selection(), paths)
        get_data.assert_called_once_with(handler._file_drop_format)

    def test_snapshot_builds_hashed_manifest_and_local_source_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "one.txt").write_bytes(b"one")
            folder = root / "folder"
            folder.mkdir()
            (folder / "two.txt").write_bytes(b"two")

            manifest, sources = snapshot_selection([root / "one.txt", folder])

            self.assertEqual(
                [item.relative_path for item in manifest.items],
                ["one.txt", "folder", "folder/two.txt"],
            )
            self.assertEqual(set(sources), {"one.txt", "folder/two.txt"})
            self.assertNotIn(str(root), repr(manifest.to_wire()))


if __name__ == "__main__":
    unittest.main()
