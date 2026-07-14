import tempfile
import unittest
from pathlib import Path

from app.trust import PeerTrustStore


class PeerTrustStoreTests(unittest.TestCase):
    def test_commits_loads_and_clears_a_canonical_peer_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = PeerTrustStore(root)
            peer = store.peer_id("  EXAMPLE.local ", 5000)

            store.commit(peer, "aa" * 32)

            self.assertEqual(store.load(peer), "aa" * 32)
            files = list(root.glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].parent.resolve(), root.resolve())
            self.assertNotIn("example.local", files[0].name)
            self.assertTrue(store.clear(peer))
            self.assertIsNone(store.load(peer))

    def test_rejects_invalid_fingerprints_without_changing_existing_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PeerTrustStore(directory)
            peer = store.peer_id("192.168.1.5", 5000)
            store.commit(peer, "11" * 32)

            with self.assertRaises(ValueError):
                store.commit(peer, "not-a-fingerprint")

            self.assertEqual(store.load(peer), "11" * 32)


if __name__ == "__main__":
    unittest.main()
