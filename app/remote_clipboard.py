import threading

from app.clipboard_formats import (
    ClipboardPayloadError,
    clipboard_message_identity,
)
from app.file_transfer.paste_coordinator import (
    OfferKind,
    PeerPayloadState,
)


class RemoteClipboardInbox:
    """Join control-lane offers with revisioned data-lane clipboard payloads."""

    def __init__(self, coordinator, inject):
        self.coordinator = coordinator
        self.inject = inject
        self._pending = None
        self._lock = threading.Lock()

    def receive_offer(self, kind, revision, session_id):
        accepted = self.coordinator.observe_peer_offer(
            kind, revision, session_id
        )
        if not accepted:
            return False

        payload = None
        with self._lock:
            pending = self._pending
            if pending is not None:
                pending_revision, pending_session, pending_payload = pending
                if (
                    OfferKind(kind) is OfferKind.ORDINARY
                    and pending_revision == revision
                    and pending_session == session_id
                ):
                    payload = pending_payload
                    self._pending = None
                elif (
                    pending_session != session_id
                    or pending_revision <= revision
                ):
                    self._pending = None
        if payload is not None:
            return self.inject(payload) is not False
        return True

    def on_local_offer(self):
        with self._lock:
            if self._pending is None:
                return False
            self._pending = None
            return True

    def receive_payload(self, payload):
        try:
            revision, session_id = clipboard_message_identity(payload)
        except ClipboardPayloadError:
            return False

        if revision is None:
            return self.inject(payload) is not False

        state = self.coordinator.peer_payload_state(
            OfferKind.ORDINARY, revision, session_id
        )
        if state is PeerPayloadState.CURRENT:
            return self.inject(payload) is not False
        if state is PeerPayloadState.STALE:
            return False

        with self._lock:
            current = self._pending
            if (
                current is None
                or current[1] != session_id
                or revision > current[0]
            ):
                self._pending = (revision, session_id, payload)
        return True

    def reset(self):
        with self._lock:
            self._pending = None
