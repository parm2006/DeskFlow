import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.clipboard_handler import ClipboardHandler
from app.file_transfer.selection import snapshot_selection
from app.file_transfer.source import SourceChangedError


class StatWithAttributes:
    def __init__(self, value, *, attributes=0, device=None, inode=None):
        self._value = value
        self.st_file_attributes = attributes
        self.st_dev = value.st_dev if device is None else device
        self.st_ino = value.st_ino if inode is None else inode

    def __getattr__(self, name):
        return getattr(self._value, name)


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

    def test_snapshot_rejects_root_and_nested_directory_reparse_points(self):
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "selected"
            nested = root / "linked"
            nested.mkdir(parents=True)
            (nested / "private.txt").write_text("private", encoding="utf-8")
            original_lstat = Path.lstat

            for flagged in (root, nested):
                with self.subTest(flagged=flagged):
                    def lstat_with_reparse(path, *, _flagged=flagged):
                        value = original_lstat(path)
                        if path == _flagged:
                            return StatWithAttributes(value, attributes=reparse)
                        return value

                    with patch.object(Path, "lstat", lstat_with_reparse):
                        with self.assertRaisesRegex(SourceChangedError, "reparse"):
                            snapshot_selection([root])

    def test_snapshot_rejects_repeated_directory_identity_as_a_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "selected"
            nested = root / "nested"
            nested.mkdir(parents=True)
            original_lstat = Path.lstat
            root_stat = original_lstat(root)

            def lstat_with_cycle(path):
                value = original_lstat(path)
                if path == nested:
                    return StatWithAttributes(
                        value, device=root_stat.st_dev, inode=root_stat.st_ino
                    )
                return value

            with patch.object(Path, "lstat", lstat_with_cycle):
                with self.assertRaisesRegex(SourceChangedError, "cycle"):
                    snapshot_selection([root])


if __name__ == "__main__":
    unittest.main()
