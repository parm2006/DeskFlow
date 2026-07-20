import unittest
import threading
from unittest.mock import patch

from app.clipboard_authority import ClipboardKind
from app.clipboard_handler import ClipboardHandler


class FileClipboardAvailabilityTests(unittest.TestCase):
    def test_default_poll_interval_acknowledges_copy_promptly(self):
        handler = ClipboardHandler(lambda snapshot: None)

        self.assertLessEqual(handler.poll_interval, 0.1)

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

    def test_remote_text_injection_does_not_announce_a_new_local_copy(self):
        changes = []
        handler = ClipboardHandler(
            lambda snapshot: None,
            on_file_availability=changes.append,
        )
        handler.file_availability = True
        handler.last_sequence_num = 11

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
        self.assertEqual(changes, [])

    def test_user_copy_during_remote_injection_remains_pending_for_poller(self):
        handler = ClipboardHandler(lambda snapshot: None)
        handler.last_sequence_num = 10
        current_sequence = [10]

        def deskflow_writes_clipboard():
            current_sequence[0] = 11

        def user_copies_after_close():
            current_sequence[0] = 12

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.EmptyClipboard",
                side_effect=deskflow_writes_clipboard,
            ),
            patch("app.clipboard_handler.win32clipboard.SetClipboardData"),
            patch(
                "app.clipboard_handler.win32clipboard.CloseClipboard",
                side_effect=user_copies_after_close,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                side_effect=lambda: current_sequence[0],
            ),
            patch("app.clipboard_handler.time.sleep") as sleep,
        ):
            self.assertTrue(handler.inject({"text": "remote"}))

        self.assertEqual(handler.last_sequence_num, 11)
        self.assertEqual(current_sequence[0], 12)
        sleep.assert_not_called()

    def test_remote_injection_does_not_call_local_availability_callback(self):
        callbacks = []

        def fail_callback(_available):
            callbacks.append(_available)
            raise RuntimeError("network unavailable")

        handler = ClipboardHandler(
            lambda snapshot: None,
            on_file_availability=fail_callback,
        )
        handler.file_availability = True
        handler.last_sequence_num = 11

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
            self.assertTrue(handler.inject({"text": "replacement"}))

        self.assertFalse(handler.is_injecting)
        self.assertEqual(callbacks, [])


class ClipboardSequenceEventTests(unittest.TestCase):
    def test_startup_does_not_publish_existing_ordinary_content(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=29,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch("app.clipboard_handler.threading.Thread") as thread,
        ):
            handler.start()

        thread.return_value.start.assert_called_once_with()
        self.assertEqual(handler.last_sequence_num, 29)
        self.assertEqual(kinds, [])
        self.assertEqual(snapshots, [])

    def test_startup_announces_existing_files_without_sending_ordinary_content(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=30,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=True,
            ),
            patch("app.clipboard_handler.threading.Thread") as thread,
        ):
            handler.start()

        thread.return_value.start.assert_called_once_with()
        self.assertEqual(handler.last_sequence_num, 30)
        self.assertEqual(kinds, [ClipboardKind.FILES])
        self.assertEqual(snapshots, [])

    def test_one_sequence_change_produces_one_acknowledged_copy(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )
        handler.last_sequence_num = 40

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=41,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch.object(handler, "_read_clipboard", return_value={"text": "one"}),
        ):
            self.assertTrue(handler.process_current_sequence())
            self.assertFalse(handler.process_current_sequence())

        self.assertEqual(kinds, [ClipboardKind.ORDINARY])
        self.assertEqual(snapshots, [{"text": "one"}])
        self.assertEqual(handler.last_sequence_num, 41)

    def test_repeated_identical_content_is_acknowledged_per_sequence(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )
        handler.last_sequence_num = 50

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                side_effect=[51, 52],
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch.object(handler, "_read_clipboard", return_value={"text": "same"}),
        ):
            self.assertTrue(handler.process_current_sequence())
            self.assertTrue(handler.process_current_sequence())

        self.assertEqual(kinds, [ClipboardKind.ORDINARY, ClipboardKind.ORDINARY])
        self.assertEqual(snapshots, [{"text": "same"}, {"text": "same"}])

    def test_inactive_sequence_is_recorded_without_publishing(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )
        handler.last_sequence_num = 60
        handler.set_active(False)

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=61,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch.object(handler, "_read_clipboard", return_value={"text": "ignored"}),
        ):
            self.assertTrue(handler.process_current_sequence())

        self.assertEqual(handler.last_sequence_num, 61)
        self.assertEqual(kinds, [])
        self.assertEqual(snapshots, [])

    def test_rich_image_and_empty_sequences_are_ordinary_copy_events(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )
        handler.last_sequence_num = 70
        expected = [{"html": b"<b>x</b>"}, {"image": b"dib"}, {}]

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                side_effect=[71, 72, 73],
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch.object(handler, "_read_clipboard", side_effect=expected),
        ):
            for _ in expected:
                self.assertTrue(handler.process_current_sequence())

        self.assertEqual(kinds, [ClipboardKind.ORDINARY] * 3)
        self.assertEqual(snapshots, expected)

    def test_failed_read_leaves_sequence_pending_for_retry(self):
        snapshots = []
        kinds = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_kind=kinds.append,
        )
        handler.last_sequence_num = 80

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=81,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
            patch.object(handler, "_read_clipboard", return_value=None),
        ):
            self.assertFalse(handler.process_current_sequence())

        self.assertEqual(handler.last_sequence_num, 80)
        self.assertEqual(kinds, [])
        self.assertEqual(snapshots, [])

    def test_locked_clipboard_read_reports_failure_instead_of_empty_content(self):
        handler = ClipboardHandler(lambda snapshot: None)

        with (
            patch(
                "app.clipboard_handler.win32clipboard.OpenClipboard",
                side_effect=RuntimeError("locked"),
            ),
            patch("app.clipboard_handler.time.sleep"),
        ):
            self.assertIsNone(handler._read_clipboard())


class ClipboardInjectionAuthorityTests(unittest.TestCase):
    def test_shared_authority_lock_serializes_remote_injection(self):
        shared_lock = threading.RLock()
        handler = ClipboardHandler(
            lambda snapshot: None,
            state_lock=shared_lock,
        )
        handler.last_sequence_num = 100
        opened = threading.Event()
        result = []

        shared_lock.acquire()
        try:
            with (
                patch(
                    "app.clipboard_handler.win32clipboard.OpenClipboard",
                    side_effect=opened.set,
                ),
                patch(
                    "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                    return_value=100,
                ),
                patch("app.clipboard_handler.win32clipboard.EmptyClipboard"),
                patch("app.clipboard_handler.win32clipboard.SetClipboardData"),
                patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
                patch(
                    "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                    return_value=False,
                ),
            ):
                worker = threading.Thread(
                    target=lambda: result.append(handler.inject({"text": "remote"}))
                )
                worker.start()
                self.assertFalse(opened.wait(0.05))
                shared_lock.release()
                worker.join(timeout=1)
        finally:
            try:
                shared_lock.release()
            except RuntimeError:
                pass

        self.assertTrue(opened.is_set())
        self.assertEqual(result, [True])

    def test_unprocessed_local_sequence_rejects_remote_write_atomically(self):
        handler = ClipboardHandler(lambda snapshot: None)
        handler.last_sequence_num = 90

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=91,
            ),
            patch("app.clipboard_handler.win32clipboard.EmptyClipboard") as empty,
            patch("app.clipboard_handler.win32clipboard.SetClipboardData") as set_data,
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch("app.clipboard_handler.time.sleep"),
        ):
            self.assertFalse(handler.inject({"text": "remote"}))

        empty.assert_not_called()
        set_data.assert_not_called()
        self.assertEqual(handler.last_sequence_num, 90)
        self.assertFalse(handler.is_injecting)

    def test_inactive_local_sequence_cannot_block_active_peer_write(self):
        handler = ClipboardHandler(lambda snapshot: None)
        handler.set_active(False)
        handler.last_sequence_num = 90

        with (
            patch("app.clipboard_handler.win32clipboard.OpenClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                side_effect=[91, 92],
            ),
            patch("app.clipboard_handler.win32clipboard.EmptyClipboard") as empty,
            patch("app.clipboard_handler.win32clipboard.SetClipboardData"),
            patch("app.clipboard_handler.win32clipboard.CloseClipboard"),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=False,
            ),
        ):
            self.assertTrue(handler.inject({"text": "active peer"}))

        empty.assert_called_once_with()
        self.assertEqual(handler.last_sequence_num, 92)


if __name__ == "__main__":
    unittest.main()
