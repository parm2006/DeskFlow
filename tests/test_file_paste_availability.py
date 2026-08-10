import unittest

from app.file_transfer.paste_coordinator import (
    OfferKind,
    PasteCoordinator,
)


class PasteCoordinatorTests(unittest.TestCase):
    def test_same_machine_files_remain_native_on_both_destinations(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste") or object())
        coordinator.reset("session-a")

        coordinator.observe_local_offer(OfferKind.FILES, 1, "session-a")
        coordinator.set_destination_is_local(True)
        coordinator.on_key_press("ctrl")
        self.assertFalse(coordinator.on_key_press("v"))
        coordinator.on_key_release("v")

        coordinator.observe_peer_offer(OfferKind.FILES, 1, "session-a")
        coordinator.set_destination_is_local(False)
        self.assertFalse(coordinator.on_key_press("v"))

        self.assertEqual(requested, [])

    def test_cross_machine_files_start_exactly_one_request(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste") or object())
        coordinator.reset("session-a")
        coordinator.observe_peer_offer(OfferKind.FILES, 1, "session-a")
        coordinator.set_destination_is_local(True)

        coordinator.on_key_press("ctrl")
        self.assertTrue(coordinator.on_key_press("v"))
        coordinator.on_key_release("v")
        self.assertTrue(coordinator.on_key_press("v"))

        self.assertEqual(requested, ["paste"])

    def test_newer_local_offer_supersedes_stale_peer_file_offer(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste") or object())
        coordinator.reset("session-a")
        coordinator.observe_peer_offer(OfferKind.FILES, 4, "session-a")
        coordinator.observe_local_offer(OfferKind.FILES, 1, "session-a")
        coordinator.set_destination_is_local(True)

        coordinator.on_key_press("ctrl")
        self.assertFalse(coordinator.on_key_press("v"))

        self.assertEqual(requested, [])

    def test_stale_revision_and_prior_session_cannot_reclaim_ownership(self):
        coordinator = PasteCoordinator(lambda: None)
        coordinator.reset("session-b")

        self.assertTrue(
            coordinator.observe_peer_offer(OfferKind.FILES, 3, "session-b")
        )
        self.assertFalse(
            coordinator.observe_peer_offer(OfferKind.ORDINARY, 2, "session-b")
        )
        self.assertFalse(
            coordinator.observe_peer_offer(OfferKind.FILES, 99, "session-a")
        )

        self.assertEqual(coordinator.current_offer.kind, OfferKind.FILES)
        self.assertEqual(coordinator.current_offer.revision, 3)

    def test_new_offer_changes_route_without_mutating_pending_request(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste") or object())
        coordinator.reset("session-a")
        coordinator.observe_peer_offer(OfferKind.FILES, 1, "session-a")
        coordinator.set_destination_is_local(True)
        coordinator.on_key_press("ctrl")
        self.assertTrue(coordinator.on_key_press("v"))
        coordinator.on_key_release("v")

        coordinator.observe_local_offer(OfferKind.FILES, 1, "session-a")
        self.assertFalse(coordinator.on_key_press("v"))

        self.assertEqual(requested, ["paste"])

    def test_intercepts_ctrl_v_only_when_remote_files_are_available(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste"))

        coordinator.set_remote_files_available(True)
        self.assertFalse(coordinator.on_key_press("ctrl"))
        self.assertTrue(coordinator.on_key_press("v"))
        self.assertEqual(requested, ["paste"])
        self.assertTrue(coordinator.on_key_release("v"))
        self.assertFalse(coordinator.on_key_release("ctrl"))

    def test_ordinary_and_repeated_paste_keys_are_not_accidentally_suppressed(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste"))

        coordinator.on_key_press("ctrl")
        self.assertFalse(coordinator.on_key_press("v"))
        coordinator.set_remote_files_available(True)
        self.assertTrue(coordinator.on_key_press("v"))
        self.assertTrue(coordinator.on_key_press("v"))
        self.assertEqual(requested, ["paste"])
        coordinator.on_key_release("v")
        coordinator.set_remote_files_available(False)
        self.assertFalse(coordinator.on_key_press("v"))

    def test_disconnect_clears_availability_and_modifier_state(self):
        coordinator = PasteCoordinator(lambda: None)
        coordinator.set_remote_files_available(True)
        coordinator.on_key_press("ctrl")
        coordinator.reset()

        self.assertFalse(coordinator.remote_files_available)
        self.assertFalse(coordinator.on_key_press("v"))


if __name__ == "__main__":
    unittest.main()
