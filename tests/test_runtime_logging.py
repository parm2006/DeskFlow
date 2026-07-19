import logging
import unittest
from unittest.mock import patch

import run
from app.gui import run_mainloop


class RuntimeLoggingTests(unittest.TestCase):
    def test_console_interrupt_runs_application_cleanup(self):
        events = []

        class App:
            def mainloop(self):
                events.append("mainloop")
                raise KeyboardInterrupt

            def on_close(self):
                events.append("close")

        with self.assertRaises(KeyboardInterrupt):
            run_mainloop(App())

        self.assertEqual(events, ["mainloop", "close"])

    def test_gui_entry_point_enables_privacy_safe_info_console_logging(self):
        with patch("run.logging.basicConfig") as configure:
            run.configure_runtime_logging()

        configure.assert_called_once_with(
            level=logging.INFO,
            format="%(levelname)s: %(message)s",
        )


if __name__ == "__main__":
    unittest.main()
