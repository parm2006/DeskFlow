import threading
from dataclasses import dataclass
from enum import Enum


class OfferKind(str, Enum):
    FILES = "files"
    ORDINARY = "ordinary"


class OfferOrigin(str, Enum):
    LOCAL = "local"
    PEER = "peer"


@dataclass(frozen=True)
class ClipboardOffer:
    origin: OfferOrigin
    kind: OfferKind
    revision: int
    session_epoch: str | None


@dataclass(frozen=True)
class PendingPaste:
    offer: ClipboardOffer
    destination_is_local: bool


class PeerPayloadState(str, Enum):
    CURRENT = "current"
    FUTURE = "future"
    STALE = "stale"


class PasteCoordinator:
    CTRL_KEYS = frozenset(("ctrl", "ctrl_l", "ctrl_r"))

    def __init__(self, on_remote_file_paste, refresh_local_offer=None):
        self.on_remote_file_paste = on_remote_file_paste
        self.refresh_local_offer = refresh_local_offer
        self.current_offer = None
        self.destination_is_local = True
        self.session_epoch = None
        self.pending_paste = None
        self._last_revision = {
            OfferOrigin.LOCAL: 0,
            OfferOrigin.PEER: 0,
        }
        self._legacy_peer_revision = 0
        self._pressed_ctrl = set()
        self._suppressing_v = False
        self._lock = threading.RLock()

    @property
    def remote_files_available(self):
        with self._lock:
            return bool(
                self.current_offer is not None
                and self.current_offer.origin is OfferOrigin.PEER
                and self.current_offer.kind is OfferKind.FILES
            )

    def observe_local_offer(self, kind, revision, session_epoch=None):
        return self._observe(
            OfferOrigin.LOCAL, kind, revision, session_epoch
        )

    def observe_peer_offer(self, kind, revision, session_epoch=None):
        return self._observe(
            OfferOrigin.PEER, kind, revision, session_epoch
        )

    def _observe(self, origin, kind, revision, session_epoch):
        try:
            kind = OfferKind(kind)
        except (TypeError, ValueError):
            return False
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
            return False
        with self._lock:
            if (
                self.session_epoch is not None
                and session_epoch != self.session_epoch
            ):
                return False
            if revision <= self._last_revision[origin]:
                return False
            self._last_revision[origin] = revision
            self.current_offer = ClipboardOffer(
                origin, kind, revision, session_epoch
            )
            return True

    def set_destination_is_local(self, is_local):
        with self._lock:
            self.destination_is_local = is_local is True

    def peer_payload_state(self, kind, revision, session_epoch):
        try:
            kind = OfferKind(kind)
        except (TypeError, ValueError):
            return PeerPayloadState.STALE
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
            return PeerPayloadState.STALE
        with self._lock:
            if (
                self.session_epoch is not None
                and session_epoch != self.session_epoch
            ):
                return PeerPayloadState.STALE
            expected = ClipboardOffer(
                OfferOrigin.PEER, kind, revision, session_epoch
            )
            if self.current_offer == expected:
                return PeerPayloadState.CURRENT
            if revision > self._last_revision[OfferOrigin.PEER]:
                return PeerPayloadState.FUTURE
            return PeerPayloadState.STALE

    def set_remote_files_available(self, available):
        """Compatibility shim for peers/tests using the legacy boolean event."""
        with self._lock:
            self._legacy_peer_revision += 1
            revision = self._legacy_peer_revision
            session_epoch = self.session_epoch
        return self.observe_peer_offer(
            OfferKind.FILES if available is True else OfferKind.ORDINARY,
            revision,
            session_epoch,
        )

    def on_key_press(self, key):
        if key in self.CTRL_KEYS:
            with self._lock:
                self._pressed_ctrl.add(key)
            return False
        if not isinstance(key, str) or key.lower() != "v":
            return False

        with self._lock:
            ctrl_pressed = bool(self._pressed_ctrl)
        if not ctrl_pressed:
            return False

        if self.refresh_local_offer is not None:
            self.refresh_local_offer()

        with self._lock:
            offer = self.current_offer
            destination_is_local = self.destination_is_local
            cross_machine_files = bool(
                offer is not None
                and offer.kind is OfferKind.FILES
                and (
                    (offer.origin is OfferOrigin.LOCAL)
                    != destination_is_local
                )
            )
            if not cross_machine_files:
                return False
            if self._suppressing_v:
                return True
            self._suppressing_v = True
            pending = PendingPaste(offer, destination_is_local)
            if self.pending_paste == pending:
                return True

        try:
            request = self.on_remote_file_paste()
        except Exception:
            with self._lock:
                self._suppressing_v = False
            raise
        if request is not None and request is not False:
            with self._lock:
                self.pending_paste = pending
        return True

    def on_key_release(self, key):
        if key in self.CTRL_KEYS:
            with self._lock:
                self._pressed_ctrl.discard(key)
            return False
        if isinstance(key, str) and key.lower() == "v":
            with self._lock:
                if self._suppressing_v:
                    self._suppressing_v = False
                    return True
        return False

    def clear_pending(self, offer=None, destination_is_local=None):
        with self._lock:
            pending = self.pending_paste
            if pending is None:
                return False
            if offer is not None and pending.offer != offer:
                return False
            if (
                destination_is_local is not None
                and pending.destination_is_local != destination_is_local
            ):
                return False
            self.pending_paste = None
            return True

    def reset(self, session_epoch=None):
        with self._lock:
            self.current_offer = None
            self.destination_is_local = True
            self.session_epoch = session_epoch
            self.pending_paste = None
            self._last_revision = {
                OfferOrigin.LOCAL: 0,
                OfferOrigin.PEER: 0,
            }
            self._legacy_peer_revision = 0
            self._pressed_ctrl.clear()
            self._suppressing_v = False
