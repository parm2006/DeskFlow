import unittest

from app.file_transfer.status import TransferPhase, TransferStatus


class TransferStatusTests(unittest.TestCase):
    def test_progress_snapshot_calculates_percent_speed_and_eta(self):
        status = TransferStatus(
            job_id="job-A",
            phase=TransferPhase.TRANSFERRING,
            label="3 files",
            bytes_done=25,
            bytes_total=100,
            bytes_per_second=10,
        )

        self.assertEqual(status.percent, 25.0)
        self.assertEqual(status.eta_seconds, 7.5)
        self.assertNotIn("path", status.to_public_dict())

    def test_terminal_and_indeterminate_phases_are_explicit(self):
        preparing = TransferStatus("job", TransferPhase.PREPARING, "file", 0, 0)
        completed = TransferStatus("job", TransferPhase.COMPLETED, "file", 10, 10)

        self.assertIsNone(preparing.percent)
        self.assertFalse(preparing.is_terminal)
        self.assertTrue(completed.is_terminal)


if __name__ == "__main__":
    unittest.main()
