import threading
import unittest

from app.latest_wins_sender import LatestWinsSender


class LatestWinsSenderTests(unittest.TestCase):
    def test_active_send_finishes_and_only_latest_pending_payload_is_sent(self):
        first_send_started = threading.Event()
        release_first_send = threading.Event()
        sent = []

        def send(payload):
            sent.append(payload)
            if payload["text"] == "A":
                first_send_started.set()
                self.assertTrue(release_first_send.wait(timeout=1))

        sender = LatestWinsSender(send)
        self.addCleanup(sender.stop)

        sender.submit({"text": "A"})
        self.assertTrue(first_send_started.wait(timeout=1))
        sender.submit({"text": "B"})
        sender.submit({"text": "C"})
        sender.submit({"text": "D"})
        release_first_send.set()

        self.assertTrue(sender.wait_until_idle(timeout=1))
        self.assertEqual(sent, [{"text": "A"}, {"text": "D"}])

    def test_submit_snapshots_payload_before_worker_sends_it(self):
        release_send = threading.Event()
        sent = []

        def send(payload):
            self.assertTrue(release_send.wait(timeout=1))
            sent.append(payload)

        sender = LatestWinsSender(send)
        self.addCleanup(sender.stop)
        payload = {"text": "original"}

        sender.submit(payload)
        payload["text"] = "mutated"
        release_send.set()

        self.assertTrue(sender.wait_until_idle(timeout=1))
        self.assertEqual(sent, [{"text": "original"}])

    def test_send_exception_does_not_kill_worker_or_leave_sender_busy(self):
        attempted = threading.Event()
        sent = []

        def send(payload):
            if payload["text"] == "bad":
                attempted.set()
                raise RuntimeError("send failed")
            sent.append(payload)

        sender = LatestWinsSender(send)
        self.addCleanup(sender.stop)

        with self.assertLogs("app.latest_wins_sender", level="ERROR") as logs:
            sender.submit({"text": "bad"})
            self.assertTrue(attempted.wait(timeout=1))
            self.assertTrue(sender.wait_until_idle(timeout=1))
        self.assertIn("Latest-wins send failed", logs.output[0])
        sender.submit({"text": "good"})

        self.assertTrue(sender.wait_until_idle(timeout=1))
        self.assertEqual(sent, [{"text": "good"}])

    def test_explicit_send_failure_retries_latest_payload(self):
        attempts = []

        def send(payload):
            attempts.append(payload)
            return len(attempts) > 1

        sender = LatestWinsSender(send)
        self.addCleanup(sender.stop)

        sender.submit({"text": "retry"})

        self.assertTrue(sender.wait_until_idle(timeout=1))
        self.assertEqual(
            attempts,
            [{"text": "retry"}, {"text": "retry"}],
        )

    def test_stop_drops_pending_payload_and_rejects_new_submissions(self):
        first_send_started = threading.Event()
        release_first_send = threading.Event()
        sent = []

        def send(payload):
            sent.append(payload)
            first_send_started.set()
            self.assertTrue(release_first_send.wait(timeout=1))

        sender = LatestWinsSender(send)
        sender.submit({"text": "active"})
        self.assertTrue(first_send_started.wait(timeout=1))
        sender.submit({"text": "pending"})

        stop_thread = threading.Thread(target=sender.stop)
        stop_thread.start()
        release_first_send.set()
        stop_thread.join(timeout=1)

        self.assertFalse(stop_thread.is_alive())
        self.assertFalse(sender.submit({"text": "late"}))
        self.assertEqual(sent, [{"text": "active"}])


if __name__ == "__main__":
    unittest.main()
