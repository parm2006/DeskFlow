import unittest

from app.file_transfer.status import TransferPhase, TransferStatus
from app.file_transfer.toast import toast_view


class TransferToastViewTests(unittest.TestCase):
    def test_verified_network_transfer_is_described_as_ready_not_pasted(self):
        status = TransferStatus("job", TransferPhase.COMPLETED, "large-file.bin", 100, 100)

        view = toast_view(status)

        self.assertEqual(view.title, "Ready in Explorer")
        self.assertIn("100 B / 100 B", view.details)
        self.assertEqual(view.hide_after_ms, 3000)

    def test_every_terminal_state_has_a_hide_deadline(self):
        for phase in (TransferPhase.COMPLETED, TransferPhase.FAILED, TransferPhase.CANCELLED):
            with self.subTest(phase=phase):
                status = TransferStatus("job", phase, "file.bin", 50, 100)
                self.assertIsNotNone(toast_view(status).hide_after_ms)

    def test_long_private_label_is_not_rendered_in_compact_title(self):
        status = TransferStatus("job", TransferPhase.TRANSFERRING, "x" * 500, 50, 100, 25)

        view = toast_view(status)

        self.assertEqual(view.title, "Transferring files")
        self.assertNotIn("x", view.title)
        self.assertLessEqual(len(view.details), 80)


if __name__ == "__main__":
    unittest.main()
