import unittest
from pathlib import Path

from app.safe_errors import error_name, public_error_message
from app.file_transfer.executor import FifoTransferExecutor


PRIVATE_PATH = r"C:\Users\private-user\Documents\sensitive-name.txt"


class SafeErrorTests(unittest.TestCase):
    def test_unknown_error_exposes_category_without_private_path(self):
        error = PermissionError(13, "Access denied", PRIVATE_PATH)

        message = public_error_message(error, "connection failed")

        self.assertEqual(message, "connection failed (PermissionError)")
        self.assertNotIn(PRIVATE_PATH, message)
        self.assertEqual(error_name(error), "PermissionError")

    def test_explicitly_public_error_retains_actionable_message(self):
        class PairingFailure(Exception):
            safe_for_user = True

        error = PairingFailure("pairing was declined")

        self.assertEqual(
            public_error_message(error, "connection failed"),
            "pairing was declined",
        )

    def test_empty_public_error_uses_the_safe_fallback(self):
        class EmptyFailure(Exception):
            safe_for_user = True

        self.assertEqual(
            public_error_message(EmptyFailure(), "connection failed"),
            "connection failed (EmptyFailure)",
        )

    def test_transfer_worker_log_omits_private_exception_details(self):
        class Sender:
            def send_job(self, manifest, sources, announce_manifest=False):
                raise PermissionError(13, "Access denied", PRIVATE_PATH)

        executor = FifoTransferExecutor(Sender())
        with self.assertLogs("app.file_transfer.executor", level="ERROR") as logs:
            executor.submit(object(), {})
            self.assertTrue(executor.wait_until_idle(1))

        output = "\n".join(logs.output)
        self.assertIn("PermissionError", output)
        self.assertNotIn(PRIVATE_PATH, output)
        self.assertNotIn("Access denied", output)

    def test_production_code_does_not_emit_exception_tracebacks(self):
        offenders = []
        for path in Path("app").rglob("*.py"):
            if "logger.exception(" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
