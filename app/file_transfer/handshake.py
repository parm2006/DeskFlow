import secrets
import time
from dataclasses import dataclass
from enum import Enum


class RequestState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


@dataclass
class ManifestRequest:
    request_id: str
    deadline: float
    state: RequestState = RequestState.PENDING
    manifest: dict | None = None
    error: str | None = None


class ManifestHandshakeQueue:
    def __init__(self, send_request, clock=time.monotonic, timeout_seconds=1.0):
        self.send_request = send_request
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self._requests = []
        self._by_id = {}

    @property
    def accepted(self):
        return tuple(request for request in self._requests if request.state is RequestState.ACCEPTED)

    def begin(self):
        request = ManifestRequest(
            request_id=secrets.token_hex(16),
            deadline=self.clock() + self.timeout_seconds,
        )
        self._requests.append(request)
        self._by_id[request.request_id] = request
        self.send_request({"type": "file_manifest_request", "request_id": request.request_id})
        return request

    def accept(self, request_id, manifest):
        request = self._by_id.get(request_id)
        if request is None or request.state is not RequestState.PENDING:
            return False
        if self.clock() > request.deadline:
            request.state = RequestState.TIMED_OUT
            return False
        request.manifest = manifest
        request.state = RequestState.ACCEPTED
        return True

    def fail(self, request_id, error):
        request = self._by_id.get(request_id)
        if request is None or request.state is not RequestState.PENDING:
            return False
        request.error = error
        request.state = RequestState.FAILED
        return True

    def expire(self):
        now = self.clock()
        expired = []
        for request in self._requests:
            if request.state is RequestState.PENDING and now > request.deadline:
                request.state = RequestState.TIMED_OUT
                expired.append(request)
        return expired
