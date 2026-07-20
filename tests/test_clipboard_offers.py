import unittest
from unittest.mock import patch

from app.clipboard_handler import ClipboardHandler
from app.clipboard_offer import ClipboardKind, ClipboardOffer, RemoteClipboardState
from app.file_transfer.paste_coordinator import PasteCoordinator


class ClipboardHandlerOfferTests(unittest.TestCase):
    def test_restarted_handler_invalidates_older_poll_generation(self):
        handler = ClipboardHandler(lambda snapshot: None)
        handler.is_running = True
        handler._run_generation = 1
        refreshes = []

        def invalidate_old_worker():
            refreshes.append("refresh")
            handler._run_generation = 2

        with (
            patch.object(
                handler, "refresh_current_offer", side_effect=invalidate_old_worker
            ),
            patch("app.clipboard_handler.time.sleep"),
        ):
            handler._poll_clipboard(1)

        self.assertEqual(refreshes, ["refresh"])

    def test_file_format_wins_over_ordinary_formats_in_same_sequence(self):
        offers = []
        snapshots = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_offer=offers.append,
        )

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=7,
            ),
            patch(
                "app.clipboard_handler.win32clipboard.IsClipboardFormatAvailable",
                return_value=True,
            ),
        ):
            offer = handler.refresh_current_offer()

        self.assertEqual(offer, ClipboardOffer(ClipboardKind.FILES, 1))
        self.assertEqual(offers, [offer])
        self.assertEqual(snapshots, [])

    def test_repeated_identical_ordinary_copies_get_new_revisions(self):
        offers = []
        snapshots = []
        handler = ClipboardHandler(
            snapshots.append,
            on_clipboard_offer=offers.append,
        )

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                side_effect=[10, 11],
            ),
            patch.object(
                handler,
                "_classify_clipboard",
                side_effect=[
                    (ClipboardKind.ORDINARY, {"text": "same"}),
                    (ClipboardKind.ORDINARY, {"text": "same"}),
                ],
            ),
        ):
            first = handler.refresh_current_offer()
            second = handler.refresh_current_offer()

        self.assertEqual([offer.revision for offer in offers], [1, 2])
        self.assertEqual(first.kind, ClipboardKind.ORDINARY)
        self.assertEqual(second.kind, ClipboardKind.ORDINARY)
        self.assertEqual(
            [snapshot["_deskflow_offer_revision"] for snapshot in snapshots],
            [1, 2],
        )

    def test_rich_only_change_is_forwarded_as_an_ordinary_offer(self):
        snapshots = []
        handler = ClipboardHandler(snapshots.append)

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=12,
            ),
            patch.object(
                handler,
                "_classify_clipboard",
                return_value=(ClipboardKind.ORDINARY, {"html": b"<b>x</b>"}),
            ),
        ):
            offer = handler.refresh_current_offer()

        self.assertEqual(offer.kind, ClipboardKind.ORDINARY)
        self.assertEqual(snapshots[0]["html"], b"<b>x</b>")

    def test_failed_classification_does_not_consume_sequence_or_revision(self):
        offers = []
        handler = ClipboardHandler(
            lambda snapshot: None,
            on_clipboard_offer=offers.append,
        )

        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=20,
            ),
            patch.object(
                handler,
                "_classify_clipboard",
                side_effect=[None, (ClipboardKind.ORDINARY, {"text": "retry"})],
            ),
        ):
            self.assertIsNone(handler.refresh_current_offer())
            offer = handler.refresh_current_offer()

        self.assertEqual(offer.revision, 1)
        self.assertEqual(handler.last_sequence_num, 20)
        self.assertEqual(offers, [offer])

    def test_failed_offer_delivery_retries_same_windows_sequence(self):
        delivered = []

        def announce(offer):
            delivered.append(offer)
            return len(delivered) > 1

        handler = ClipboardHandler(
            lambda snapshot: True,
            on_clipboard_offer=announce,
        )
        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=30,
            ),
            patch.object(
                handler,
                "_classify_clipboard",
                return_value=(ClipboardKind.ORDINARY, {"text": "retry"}),
            ),
        ):
            first = handler.refresh_current_offer()
            second = handler.refresh_current_offer()

        self.assertEqual([first.revision, second.revision], [1, 2])
        self.assertEqual(len(delivered), 2)

    def test_empty_ordinary_clipboard_is_forwarded_with_revision(self):
        snapshots = []
        handler = ClipboardHandler(snapshots.append)
        with (
            patch(
                "app.clipboard_handler.win32clipboard.GetClipboardSequenceNumber",
                return_value=31,
            ),
            patch.object(
                handler,
                "_classify_clipboard",
                return_value=(ClipboardKind.ORDINARY, {}),
            ),
        ):
            handler.refresh_current_offer()

        self.assertEqual(snapshots, [{"_deskflow_offer_revision": 1}])


class RemoteClipboardStateTests(unittest.TestCase):
    def test_payload_waits_for_matching_ordinary_offer(self):
        state = RemoteClipboardState()
        payload = {"type": "clipboard_sync", "offer_revision": 3, "text": "new"}

        self.assertIsNone(state.receive_payload(payload))
        applied = state.receive_offer(
            {"type": "clipboard_offer", "kind": "ordinary", "revision": 3}
        )

        self.assertEqual(applied, (ClipboardOffer(ClipboardKind.ORDINARY, 3), payload))

    def test_newer_file_offer_discards_delayed_ordinary_payload(self):
        state = RemoteClipboardState()
        state.receive_offer(
            {"type": "clipboard_offer", "kind": "ordinary", "revision": 4}
        )
        state.receive_offer(
            {"type": "clipboard_offer", "kind": "files", "revision": 5}
        )

        self.assertIsNone(
            state.receive_payload(
                {"type": "clipboard_sync", "offer_revision": 4, "text": "stale"}
            )
        )
        self.assertEqual(state.current, ClipboardOffer(ClipboardKind.FILES, 5))

    def test_newer_ordinary_offer_supersedes_file_offer_before_payload_arrives(self):
        state = RemoteClipboardState()
        state.receive_offer(
            {"type": "clipboard_offer", "kind": "files", "revision": 8}
        )

        applied = state.receive_offer(
            {"type": "clipboard_offer", "kind": "ordinary", "revision": 9}
        )
        payload = {"type": "clipboard_sync", "offer_revision": 9, "text": "latest"}

        self.assertEqual(
            applied,
            (ClipboardOffer(ClipboardKind.ORDINARY, 9), None),
        )
        self.assertEqual(state.receive_payload(payload), payload)


class PasteRefreshTests(unittest.TestCase):
    def test_failed_synchronous_refresh_allows_native_ctrl_v(self):
        requested = []
        coordinator = PasteCoordinator(
            lambda: requested.append("paste"),
            refresh_before_paste=lambda: False,
        )
        coordinator.set_remote_files_available(True)

        coordinator.on_key_press("ctrl")

        self.assertFalse(coordinator.on_key_press("v"))
        self.assertEqual(requested, [])

    def test_successful_refresh_rechecks_latest_interception_state(self):
        requested = []
        coordinator = None

        def refresh():
            coordinator.set_remote_files_available(False)
            return True

        coordinator = PasteCoordinator(
            lambda: requested.append("paste"),
            refresh_before_paste=refresh,
        )
        coordinator.set_remote_files_available(True)
        coordinator.on_key_press("ctrl")

        self.assertFalse(coordinator.on_key_press("v"))
        self.assertEqual(requested, [])


if __name__ == "__main__":
    unittest.main()
