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

    def test_remote_text_injection_announces_that_local_file_offer_was_replaced(self):
        changes = []
        handler = ClipboardHandler(
            lambda snapshot: None,
            on_file_availability=changes.append,
        )
        handler.file_availability = True

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch("app.clipboard_handler.win32clipboard.EmptyClipboard"),
            patch("app.clipboard_handler.win32clipboard.SetClipboardData"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=11,
            ),
            patch("app.clipboard_handler.time.sleep"),
        ):
            handler.inject({"text": "replacement"})

        self.assertFalse(handler.file_availability)
        self.assertEqual(changes, [False])

    def test_user_copy_during_remote_injection_remains_pending_for_poller(self):
        handler = ClipboardHandler(lambda snapshot: None)
        handler.last_sequence_num = 10
        current_sequence = [11]

        def user_copies_while_injection_settles(_delay):
            current_sequence[0] = 12

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch("app.clipboard_handler.win32clipboard.EmptyClipboard"),
            patch("app.clipboard_handler.win32clipboard.SetClipboardData"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                side_effect=lambda: current_sequence[0],
            ),
            patch(
                "app.clipboard_handler.time.sleep",
                side_effect=user_copies_while_injection_settles,
            ),
        ):
            handler.inject({"text": "remote"})

        self.assertEqual(handler.last_sequence_num, 11)
        self.assertEqual(current_sequence[0], 12)

    def test_availability_callback_failure_does_not_wedge_injection(self):
        def fail_callback(_available):
            raise RuntimeError("network unavailable")

        handler = ClipboardHandler(
            lambda snapshot: None,
            on_file_availability=fail_callback,
        )
        handler.file_availability = True

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch("app.clipboard_handler.win32clipboard.EmptyClipboard"),
            patch("app.clipboard_handler.win32clipboard.SetClipboardData"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=11,
            ),
            patch("app.clipboard_handler.time.sleep"),
        ):
            with self.assertRaises(RuntimeError):
                handler.inject({"text": "replacement"})

        self.assertFalse(handler.is_injecting)


if __name__ == "__main__":
    unittest.main()
