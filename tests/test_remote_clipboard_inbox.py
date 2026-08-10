import unittest

from app.clipboard_formats import (
    ClipboardEntry,
    ClipboardSnapshot,
    encode_clipboard_message,
)
from app.file_transfer.paste_coordinator import OfferKind, PasteCoordinator
from app.remote_clipboard import RemoteClipboardInbox


def message(revision, session_id="session-a"):
    return encode_clipboard_message(
        ClipboardSnapshot([ClipboardEntry("unicode_text", b"text")]),
        offer_revision=revision,
        session_id=session_id,
    )


class RemoteClipboardInboxTests(unittest.TestCase):
    def make_inbox(self):
        injected = []
        coordinator = PasteCoordinator(lambda: None)
        coordinator.reset("session-a")
        inbox = RemoteClipboardInbox(coordinator, injected.append)
        return coordinator, inbox, injected

    def test_payload_before_offer_is_injected_when_matching_offer_arrives(self):
        _, inbox, injected = self.make_inbox()
        payload = message(3)

        self.assertTrue(inbox.receive_payload(payload))
        self.assertEqual(injected, [])
        self.assertTrue(inbox.receive_offer(OfferKind.ORDINARY, 3, "session-a"))

        self.assertEqual(injected, [payload])

    def test_newer_local_copy_discards_delayed_peer_payload(self):
        coordinator, inbox, injected = self.make_inbox()
        inbox.receive_offer(OfferKind.ORDINARY, 3, "session-a")
        coordinator.observe_local_offer(OfferKind.FILES, 1, "session-a")

        self.assertFalse(inbox.receive_payload(message(3)))

        self.assertEqual(injected, [])

    def test_newer_peer_file_offer_discards_pending_ordinary_payload(self):
        _, inbox, injected = self.make_inbox()
        inbox.receive_payload(message(3))

        inbox.receive_offer(OfferKind.FILES, 4, "session-a")
        self.assertFalse(
            inbox.receive_offer(OfferKind.ORDINARY, 3, "session-a")
        )

        self.assertEqual(injected, [])

    def test_local_copy_discards_future_remote_payload_waiting_for_offer(self):
        coordinator, inbox, injected = self.make_inbox()
        inbox.receive_payload(message(3))

        self.assertTrue(inbox.on_local_offer())
        coordinator.observe_local_offer(OfferKind.FILES, 1, "session-a")

        self.assertTrue(
            inbox.receive_offer(OfferKind.ORDINARY, 3, "session-a")
        )
        self.assertEqual(injected, [])

    def test_prior_session_payload_is_rejected(self):
        _, inbox, injected = self.make_inbox()

        self.assertFalse(inbox.receive_payload(message(9, "session-old")))

        self.assertEqual(injected, [])


if __name__ == "__main__":
    unittest.main()
