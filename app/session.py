"""One logical DeskFlow session shared by its independent network lanes."""

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
import uuid


class SessionAuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class SessionOffer:
    session_id: str
    data_token: str
    file_token: str


class SessionCoordinator:
    def __init__(self, password, clock=time.monotonic, token_ttl=10.0):
        self._password = str(password)
        self._clock = clock
        self._token_ttl = float(token_ttl)
        self._tokens = {}
        self._active_session = None
        self._lock = threading.Lock()

    def authenticate_control(self, candidate):
        if not isinstance(candidate, str) or not hmac.compare_digest(
            candidate.encode("utf-8"), self._password.encode("utf-8")
        ):
            raise SessionAuthenticationError("authentication failed")
        with self._lock:
            self._tokens.clear()
            session_id = uuid.uuid4().hex
            self._active_session = session_id
            data = self._issue_locked(session_id, "data")
            file_token = self._issue_locked(session_id, "file")
            return SessionOffer(session_id, data, file_token)

    def consume_lane(self, token, purpose, session_id):
        if not isinstance(token, str) or not isinstance(session_id, str):
            raise SessionAuthenticationError("lane token is invalid")
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        with self._lock:
            record = self._tokens.pop(digest, None)
            if record is None:
                raise SessionAuthenticationError("lane token is invalid or already used")
            expected_session, expected_purpose, expires = record
            if self._clock() > expires:
                raise SessionAuthenticationError("lane token expired")
            if expected_session != session_id or expected_purpose != purpose:
                raise SessionAuthenticationError("lane token belongs to another session or lane")
            if session_id != self._active_session:
                raise SessionAuthenticationError("session is no longer active")
            return True

    def close(self, session_id=None):
        with self._lock:
            if session_id is not None and session_id != self._active_session:
                return False
            self._active_session = None
            self._tokens.clear()
            return True

    @property
    def active_session_id(self):
        with self._lock:
            return self._active_session

    def _issue_locked(self, session_id, purpose):
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        self._tokens[digest] = (
            session_id,
            purpose,
            self._clock() + self._token_ttl,
        )
        return token
