import unittest

from app.clipboard_authority import (
    ClipboardAuthority,
    ClipboardKind,
    ClipboardOrigin,
)


class ClipboardAuthorityTests(unittest.TestCase):
    def test_inactive_local_change_cannot_claim_authority(self):
        authority = ClipboardAuthority(local_active=False)

        self.assertFalse(authority.note_local_copy(ClipboardKind.ORDINARY))
        self.assertEqual(authority.origin, ClipboardOrigin.UNKNOWN)
        self.assertIsNone(authority.kind)

    def test_active_local_copy_blocks_delayed_remote_copy(self):
        authority = ClipboardAuthority(local_active=True)

        self.assertTrue(authority.note_local_copy(ClipboardKind.ORDINARY))

        self.assertFalse(authority.note_remote_copy(ClipboardKind.FILES))
        self.assertEqual(authority.origin, ClipboardOrigin.LOCAL)
        self.assertEqual(authority.kind, ClipboardKind.ORDINARY)

    def test_switching_screens_preserves_authority_until_a_copy_occurs(self):
        authority = ClipboardAuthority(local_active=True)
        authority.note_local_copy(ClipboardKind.FILES)

        authority.set_local_active(False)

        self.assertEqual(authority.origin, ClipboardOrigin.LOCAL)
        self.assertEqual(authority.kind, ClipboardKind.FILES)
        self.assertTrue(authority.note_remote_copy(ClipboardKind.ORDINARY))
        self.assertEqual(authority.origin, ClipboardOrigin.REMOTE)
        self.assertEqual(authority.kind, ClipboardKind.ORDINARY)

    def test_remote_copy_remains_acceptable_after_local_screen_reactivates(self):
        authority = ClipboardAuthority(local_active=False)
        authority.note_remote_copy(ClipboardKind.FILES)

        authority.set_local_active(True)

        self.assertTrue(authority.may_accept_remote())
        self.assertTrue(authority.note_remote_copy(ClipboardKind.ORDINARY))
        self.assertEqual(authority.origin, ClipboardOrigin.REMOTE)

    def test_remote_file_state_blocks_delayed_ordinary_payload(self):
        authority = ClipboardAuthority(local_active=True)
        authority.note_remote_copy(ClipboardKind.FILES)

        self.assertFalse(authority.may_accept_remote_ordinary())

    def test_reset_clears_copy_authority_without_changing_screen_activity(self):
        authority = ClipboardAuthority(local_active=True)
        authority.note_local_copy(ClipboardKind.FILES)

        authority.reset()

        self.assertTrue(authority.local_active)
        self.assertEqual(authority.origin, ClipboardOrigin.UNKNOWN)
        self.assertIsNone(authority.kind)


if __name__ == "__main__":
    unittest.main()
