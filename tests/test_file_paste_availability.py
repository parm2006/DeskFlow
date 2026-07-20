import unittest

from app.file_transfer.paste_coordinator import PasteCoordinator


class PasteCoordinatorTests(unittest.TestCase):
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

    def test_ctrl_c_pending_copy_allows_native_paste_after_file_copy(self):
        requested = []
        now = [10.0]
        coordinator = PasteCoordinator(
            lambda: requested.append("paste"),
            clock=lambda: now[0],
        )
        coordinator.set_remote_files_available(True)

        self.assertFalse(coordinator.on_key_press("ctrl"))
        self.assertFalse(coordinator.on_key_press("c"))
        self.assertFalse(coordinator.on_key_press("v"))

        self.assertEqual(requested, [])

    def test_confirmed_ordinary_copy_disables_file_interception(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste"))
        coordinator.set_remote_files_available(True)
        coordinator.on_key_press("ctrl")
        coordinator.on_key_press("c")

        coordinator.confirm_files_available(False)

        self.assertFalse(coordinator.copy_pending)
        self.assertFalse(coordinator.on_key_press("v"))
        self.assertEqual(requested, [])

    def test_confirmed_file_copy_enables_file_interception(self):
        requested = []
        coordinator = PasteCoordinator(lambda: requested.append("paste"))
        coordinator.on_key_press("ctrl")
        coordinator.on_key_press("c")

        coordinator.confirm_files_available(True)

        self.assertFalse(coordinator.copy_pending)
        self.assertTrue(coordinator.on_key_press("v"))
        self.assertEqual(requested, ["paste"])

    def test_unconfirmed_copy_intent_expires_to_previous_file_state(self):
        requested = []
        now = [20.0]
        coordinator = PasteCoordinator(
            lambda: requested.append("paste"),
            clock=lambda: now[0],
            copy_pending_timeout=0.25,
        )
        coordinator.set_remote_files_available(True)
        coordinator.on_key_press("ctrl")
        coordinator.on_key_press("c")

        now[0] = 20.3

        self.assertTrue(coordinator.on_key_press("v"))
        self.assertEqual(requested, ["paste"])

    def test_reset_clears_pending_copy_state(self):
        coordinator = PasteCoordinator(lambda: None)
        coordinator.set_remote_files_available(True)
        coordinator.on_key_press("ctrl")
        coordinator.on_key_press("c")

        coordinator.reset()

        self.assertFalse(coordinator.copy_pending)
        self.assertFalse(coordinator.remote_files_available)


if __name__ == "__main__":
    unittest.main()
