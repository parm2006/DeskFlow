import unittest

from app.file_transfer.paste_coordinator import PasteCoordinator


class PasteCoordinatorTests(unittest.TestCase):
    def test_logs_interception_state_and_ctrl_v_routing(self):
        coordinator = PasteCoordinator(lambda: None)

        with self.assertLogs(
            "app.file_transfer.paste_coordinator", level="INFO"
        ) as logs:
            coordinator.set_remote_files_available(True)
            coordinator.on_key_press("ctrl")
            coordinator.on_key_press("v")
            coordinator.set_remote_files_available(False)

        output = "\n".join(logs.output)
        self.assertIn("File-paste interception changed: enabled=true", output)
        self.assertIn("Ctrl+V routed to remote file paste", output)
        self.assertIn("File-paste interception changed: enabled=false", output)

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
