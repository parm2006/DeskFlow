import threading
import unittest

from app.file_transfer.controller import TransferCancelled
from app.file_transfer.executor import FifoTransferExecutor


class BlockingSender:
    def __init__(self):
        self.started = []
        self.finished = []
        self.release_first = threading.Event()

    def send_job(self, manifest, sources, announce_manifest=False):
        self.started.append(manifest)
        if manifest == "A":
            self.release_first.wait(1)
        self.finished.append(manifest)


class FifoTransferExecutorTests(unittest.TestCase):
    def test_only_one_job_runs_and_later_jobs_preserve_fifo_order(self):
        sender = BlockingSender()
        executor = FifoTransferExecutor(sender)

        executor.submit("A", {})
        executor.submit("B", {})
        executor.submit("C", {})

        self.assertTrue(executor.wait_until_started("A", timeout=1))
        self.assertEqual(sender.started, ["A"])
        sender.release_first.set()
        self.assertTrue(executor.wait_until_idle(timeout=1))
        self.assertEqual(sender.started, ["A", "B", "C"])
        self.assertEqual(sender.finished, ["A", "B", "C"])

    def test_expected_cancellation_is_not_logged_as_failure_and_queue_continues(self):
        class CancellingSender:
            def __init__(self):
                self.started = []

            def send_job(self, manifest, sources, announce_manifest=False):
                self.started.append(manifest)
                if manifest == "cancelled":
                    raise TransferCancelled(manifest)

        sender = CancellingSender()
        executor = FifoTransferExecutor(sender)

        with self.assertNoLogs("app.file_transfer.executor", level="ERROR"):
            executor.submit("cancelled", {})
            executor.submit("next", {})
            self.assertTrue(executor.wait_until_idle(timeout=1))

        self.assertEqual(sender.started, ["cancelled", "next"])


if __name__ == "__main__":
    unittest.main()
