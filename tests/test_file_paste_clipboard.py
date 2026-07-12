import unittest
from unittest.mock import patch

from app.clipboard_handler import ClipboardHandler


class FileClipboardAvailabilityTests(unittest.TestCase):
    def test_emits_boolean_only_when_file_availability_changes(self):
        changes = []
        handler = ClipboardHandler(lambda snapshot: None, on_file_availability=changes.append)

        with patch("app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable", side_effect=[True, True, False]):
            handler._update_file_availability()
            handler._update_file_availability()
            handler._update_file_availability()

        self.assertEqual(changes, [True, False])

    def test_file_detection_does_not_read_or_serialize_file_paths(self):
        changes = []
        handler = ClipboardHandler(lambda snapshot: None, on_file_availability=changes.append)

        with patch("app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable", return_value=True), patch(
            "app.clipboard_handler.win32clipboard.GetClipboardData"
        ) as get_data:
            handler._update_file_availability()

        get_data.assert_not_called()
        self.assertEqual(changes, [True])


if __name__ == "__main__":
    unittest.main()
