from dataclasses import dataclass
from enum import Enum


class ClipboardKind(str, Enum):
    UNKNOWN = "unknown"
    ORDINARY = "ordinary"
    FILES = "files"


@dataclass(frozen=True)
class ClipboardOffer:
    kind: ClipboardKind
    revision: int


def parse_clipboard_offer(message):
    revision = message.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return None
    try:
        kind = ClipboardKind(message.get("kind"))
    except (TypeError, ValueError):
        return None
    if kind is ClipboardKind.UNKNOWN:
        return None
    return ClipboardOffer(kind, revision)


class RemoteClipboardState:
    """Correlate ordered offer metadata with ordinary data-lane payloads."""

    def __init__(self):
        self.current = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        self._pending_payload = None

    def reset(self):
        self.current = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        self._pending_payload = None

    def receive_offer(self, message):
        offer = parse_clipboard_offer(message)
        if offer is None or offer.revision <= self.current.revision:
            return None

        self.current = offer
        payload = None
        if self._pending_payload is not None:
            pending_revision = self._payload_revision(self._pending_payload)
            if pending_revision == offer.revision and offer.kind is ClipboardKind.ORDINARY:
                payload = self._pending_payload
            if pending_revision <= offer.revision:
                self._pending_payload = None
        return offer, payload

    def receive_payload(self, message):
        revision = self._payload_revision(message)
        if revision is None or revision < self.current.revision:
            return None
        if revision == self.current.revision:
            if self.current.kind is ClipboardKind.ORDINARY:
                return message
            return None

        if (
            self._pending_payload is None
            or revision > self._payload_revision(self._pending_payload)
        ):
            self._pending_payload = dict(message)
        return None

    @staticmethod
    def _payload_revision(message):
        revision = message.get("offer_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            return None
        return revision
