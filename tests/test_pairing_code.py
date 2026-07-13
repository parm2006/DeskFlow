import unittest

from app.crypto import pairing_code, pairing_code_from_fingerprint


class PairingCodeTests(unittest.TestCase):
    def test_pairing_code_is_stable_and_human_readable(self):
        fingerprint = "aa:bb:cc:dd:ee:ff:00:11:22:33:44:55"
        self.assertEqual(pairing_code(fingerprint), "AABB-CCDD-EEFF")
        self.assertEqual(pairing_code_from_fingerprint(fingerprint), "AABB-CCDD-EEFF")

    def test_pairing_code_rejects_short_or_invalid_values(self):
        self.assertEqual(pairing_code("not-a-fingerprint"), "")
        self.assertEqual(pairing_code("aa:bb"), "")
