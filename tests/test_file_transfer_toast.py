import unittest

from app.file_transfer.status import TransferPhase, TransferStatus
from app.file_transfer.toast import TransferToast, toast_view


class TransferToastViewTests(unittest.TestCase):
    def test_terminal_hide_is_scheduled_even_when_positioning_fails_later(self):
        callbacks = []

        class Root:
            def after(self, delay, callback):
                callbacks.append((delay, callback))
                return "timer"

        toast = TransferToast.__new__(TransferToast)
        toast.root = Root()
        toast._hide_after = None

        toast._schedule_hide(0)

        self.assertEqual(callbacks[0][0], 0)
        self.assertEqual(toast._hide_after, "timer")

    def test_full_explorer_consumption_is_described_as_copy_complete(self):
        status = TransferStatus("job", TransferPhase.COMPLETED, "large-file.bin", 100, 100)

        view = toast_view(status)

        self.assertEqual(view.title, "Copy complete")
        self.assertIn("100 B / 100 B", view.details)
        self.assertNotIn("prompt", view.details)
        self.assertEqual(view.hide_after_ms, 3000)

    def test_waiting_for_explorer_shows_no_network_numbers(self):
        status = TransferStatus(
            "job", TransferPhase.WAITING_FOR_EXPLORER, "file.bin",
            64 * 1024 * 1024, 64 * 1024 * 1024, 10 * 1024 * 1024,
        )
        view = toast_view(status)
        self.assertEqual(view.title, "Waiting for Windows Explorer")
        self.assertEqual(view.details, "Choose any Windows file prompt to continue")

    def test_every_terminal_state_has_a_hide_deadline(self):
        for phase in (TransferPhase.COMPLETED, TransferPhase.FAILED, TransferPhase.CANCELLED):
            with self.subTest(phase=phase):
                status = TransferStatus("job", phase, "file.bin", 50, 100)
                self.assertIsNotNone(toast_view(status).hide_after_ms)

    def test_explorer_timeout_uses_safe_text_and_hides_after_three_seconds(self):
        status = TransferStatus(
            "job",
            TransferPhase.FAILED,
            "private-file-name.bin",
            0,
            100,
            error_code="ExplorerStartTimeout",
        )

        view = toast_view(status)

        self.assertEqual(view.details, "Windows Explorer did not accept the paste.")
        self.assertEqual(view.hide_after_ms, 3000)
        self.assertNotIn("private-file-name", view.details)

    def test_confirmed_cancellation_hides_immediately(self):
        status = TransferStatus("job", TransferPhase.CANCELLED, "file.bin", 50, 100)
        self.assertEqual(toast_view(status).hide_after_ms, 0)

    def test_long_private_label_is_not_rendered_in_compact_title(self):
        status = TransferStatus("job", TransferPhase.TRANSFERRING, "x" * 500, 50, 100, 25)

        view = toast_view(status)

        self.assertEqual(view.title, "Network transfer")
        self.assertNotIn("x", view.title)
        self.assertLessEqual(len(view.details), 80)


if __name__ == "__main__":
    unittest.main()
