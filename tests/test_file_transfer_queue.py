import unittest

from app.file_transfer.queue import FileJobQueue, JobState


class FileJobQueueTests(unittest.TestCase):
    def test_jobs_run_fifo_and_clipboard_events_do_not_replace_them(self):
        queue = FileJobQueue()
        queue.submit("A")
        queue.submit("B")
        queue.submit("C")

        self.assertEqual(queue.start_next().job_id, "A")
        queue.note_clipboard_changed()
        self.assertEqual(queue.complete_active().state, JobState.COMPLETED)
        self.assertEqual(queue.start_next().job_id, "B")
        self.assertEqual(queue.complete_active().state, JobState.COMPLETED)
        self.assertEqual(queue.start_next().job_id, "C")

    def test_cancel_pending_job_preserves_order_and_active_job(self):
        queue = FileJobQueue()
        queue.submit("A")
        queue.submit("B")
        queue.submit("C")
        queue.start_next()

        cancelled = queue.cancel("B")

        self.assertEqual(cancelled.state, JobState.CANCELLED)
        self.assertEqual(queue.active.job_id, "A")
        queue.complete_active()
        self.assertEqual(queue.start_next().job_id, "C")

    def test_failed_job_has_bounded_retries_before_queue_advances(self):
        queue = FileJobQueue(max_retries=1)
        queue.submit("A")
        queue.submit("B")
        queue.start_next()

        self.assertEqual(queue.fail_active("temporary").state, JobState.PENDING)
        self.assertEqual(queue.start_next().job_id, "A")
        failed = queue.fail_active("permanent")

        self.assertEqual(failed.state, JobState.FAILED)
        self.assertEqual(failed.error, "permanent")
        self.assertEqual(queue.start_next().job_id, "B")


if __name__ == "__main__":
    unittest.main()
