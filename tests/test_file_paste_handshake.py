import time
import unittest

from app.file_transfer.handshake import ManifestHandshakeQueue, RequestState


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class ManifestHandshakeTests(unittest.TestCase):
    def test_state_callback_reports_pending_and_terminal_timeout(self):
        clock = FakeClock()
        observed = []
        queue = ManifestHandshakeQueue(
            lambda message: True,
            clock=clock,
            timeout_seconds=1.0,
            on_state_change=lambda request: observed.append(request.state),
        )

        queue.begin()
        clock.value += 1.01
        queue.expire()

        self.assertEqual(
            observed,
            [RequestState.PENDING, RequestState.TIMED_OUT],
        )

    def test_status_callback_failure_does_not_drop_manifest_request(self):
        sent = []

        def fail_status(_request):
            raise RuntimeError("UI unavailable")

        queue = ManifestHandshakeQueue(
            sent.append,
            on_state_change=fail_status,
        )

        with self.assertLogs(
            "app.file_transfer.handshake", level="ERROR"
        ) as logs:
            request = queue.begin()

        self.assertEqual(sent[0]["request_id"], request.request_id)
        self.assertIn("RuntimeError", logs.output[0])

    def test_preparation_timeout_must_be_finite_and_positive(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(
                    ValueError, "timeout must be finite and positive"
                ):
                    ManifestHandshakeQueue(
                        lambda message: None, timeout_seconds=timeout
                    )

    def test_pending_request_count_is_bounded_and_expiry_releases_capacity(self):
        clock = FakeClock()
        queue = ManifestHandshakeQueue(
            lambda message: None, clock=clock, timeout_seconds=1.0
        )
        requests = [queue.begin() for _ in range(8)]

        with self.assertRaisesRegex(RuntimeError, "pending manifest request limit"):
            queue.begin()

        clock.value += 1.01
        queue.expire()
        replacement = queue.begin()
        self.assertNotIn(replacement.request_id, {item.request_id for item in requests})

    def test_request_deadline_automatically_removes_lookup_entry(self):
        queue = ManifestHandshakeQueue(
            lambda message: None, timeout_seconds=0.02
        )
        request = queue.begin()

        deadline = time.monotonic() + 1.0
        while request.request_id in queue._by_id and time.monotonic() < deadline:
            time.sleep(0.005)

        self.assertNotIn(request.request_id, queue._by_id)
        self.assertEqual(request.state, RequestState.TIMED_OUT)

    def test_failed_request_send_releases_pending_state_immediately(self):
        queue = ManifestHandshakeQueue(lambda message: False)

        request = queue.begin()

        self.assertEqual(request.state, RequestState.FAILED)
        self.assertEqual(request.error, "manifest request send failed")
        self.assertNotIn(request.request_id, queue._by_id)

    def test_each_ctrl_v_creates_distinct_fifo_request(self):
        sent = []
        clock = FakeClock()
        queue = ManifestHandshakeQueue(sent.append, clock=clock)

        first = queue.begin()
        second = queue.begin()

        self.assertNotEqual(first.request_id, second.request_id)
        self.assertEqual([message["request_id"] for message in sent], [first.request_id, second.request_id])
        queue.accept(first.request_id, {"job_id": "A"})
        queue.accept(second.request_id, {"job_id": "B"})
        self.assertEqual(
            [request.state for request in queue.accepted],
            [RequestState.ACCEPTED, RequestState.ACCEPTED],
        )

    def test_accepted_request_does_not_retain_the_manifest_payload(self):
        queue = ManifestHandshakeQueue(lambda message: None)
        request = queue.begin()
        manifest = {"job_id": "a" * 32, "items": ["large payload"]}

        self.assertTrue(queue.accept(request.request_id, manifest))

        self.assertIsNone(request.manifest)

    def test_request_times_out_after_one_second_and_late_reply_is_ignored(self):
        clock = FakeClock()
        queue = ManifestHandshakeQueue(
            lambda message: None, clock=clock, timeout_seconds=1.0
        )
        request = queue.begin()
        clock.value += 1.01

        expired = queue.expire()

        self.assertEqual(expired, [request])
        self.assertEqual(request.state, RequestState.TIMED_OUT)
        self.assertFalse(queue.accept(request.request_id, {"job_id": "late"}))

    def test_default_deadline_allows_preparation_beyond_one_second(self):
        clock = FakeClock()
        queue = ManifestHandshakeQueue(lambda message: None, clock=clock)
        request = queue.begin()
        clock.value += 1.01

        self.assertEqual(queue.timeout_seconds, 120.0)
        self.assertTrue(queue.accept(request.request_id, {"job_id": "ready"}))
        self.assertEqual(request.state, RequestState.ACCEPTED)

    def test_failure_releases_request_without_creating_job(self):
        queue = ManifestHandshakeQueue(lambda message: None)
        request = queue.begin()

        queue.fail(request.request_id, "clipboard unavailable")

        self.assertEqual(request.state, RequestState.FAILED)
        self.assertEqual(request.error, "clipboard unavailable")
        self.assertEqual(queue.accepted, ())

    def test_cancellation_releases_requests_and_ignores_late_responses(self):
        queue = ManifestHandshakeQueue(lambda message: None)
        requests = [queue.begin(), queue.begin()]

        self.assertTrue(queue.cancel(requests[0].request_id))
        cancelled = queue.cancel_all()

        self.assertEqual(cancelled, [requests[1]])
        self.assertEqual(queue._by_id, {})
        self.assertTrue(
            all(request.state.value == "cancelled" for request in requests)
        )
        self.assertFalse(queue.accept(requests[0].request_id, {"job_id": "late"}))


if __name__ == "__main__":
    unittest.main()
