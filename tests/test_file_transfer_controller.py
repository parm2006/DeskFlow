import unittest

from app.file_transfer.controller import TransferCancelled, TransferController
from app.file_transfer.status import TransferPhase


class TransferControllerTests(unittest.TestCase):
    def test_emits_privacy_safe_current_transfer_snapshots(self):
        observed = []
        controller = TransferController()
        controller.subscribe(observed.append)

        controller.update("job-A", TransferPhase.TRANSFERRING, "3 files", 25, 100, 10)

        self.assertEqual(observed[-1].job_id, "job-A")
        self.assertEqual(observed[-1].percent, 25.0)
        self.assertNotIn("path", observed[-1].to_public_dict())

    def test_cancel_is_job_scoped_and_check_raises(self):
        controller = TransferController()
        controller.update("job-A", TransferPhase.TRANSFERRING, "file.bin", 0, 100)
        controller.update("job-B", TransferPhase.PREPARING, "other.bin", 0, 100)

        self.assertTrue(controller.cancel("job-A"))
        with self.assertRaises(TransferCancelled):
            controller.check_cancelled("job-A")
        controller.check_cancelled("job-B")
        self.assertEqual(controller.status("job-A").phase, TransferPhase.CANCELLED)


if __name__ == "__main__":
    unittest.main()
