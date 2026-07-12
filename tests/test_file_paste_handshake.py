import unittest

from app.file_transfer.handshake import ManifestHandshakeQueue, RequestState


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class ManifestHandshakeTests(unittest.TestCase):
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
        self.assertEqual([request.manifest["job_id"] for request in queue.accepted], ["A", "B"])

    def test_request_times_out_after_one_second_and_late_reply_is_ignored(self):
        clock = FakeClock()
        queue = ManifestHandshakeQueue(lambda message: None, clock=clock)
        request = queue.begin()
        clock.value += 1.01

        expired = queue.expire()

        self.assertEqual(expired, [request])
        self.assertEqual(request.state, RequestState.TIMED_OUT)
        self.assertFalse(queue.accept(request.request_id, {"job_id": "late"}))

    def test_failure_releases_request_without_creating_job(self):
        queue = ManifestHandshakeQueue(lambda message: None)
        request = queue.begin()

        queue.fail(request.request_id, "clipboard unavailable")

        self.assertEqual(request.state, RequestState.FAILED)
        self.assertEqual(request.error, "clipboard unavailable")
        self.assertEqual(queue.accepted, ())


if __name__ == "__main__":
    unittest.main()
