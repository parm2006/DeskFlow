import hashlib
import unittest

from app.file_transfer.protocol import (
    AuthenticationError,
    FrameError,
    SessionAuthenticator,
    decode_frame,
    encode_frame,
    verify_certificate_fingerprint,
)


class AuthenticationTests(unittest.TestCase):
    def test_session_token_is_single_use(self):
        authenticator = SessionAuthenticator("secret-token")

        authenticator.authenticate("secret-token")
        with self.assertRaises(AuthenticationError):
            authenticator.authenticate("secret-token")

    def test_certificate_fingerprint_is_required_and_must_match(self):
        certificate = b"peer certificate"
        fingerprint = hashlib.sha256(certificate).hexdigest()

        verify_certificate_fingerprint(certificate, fingerprint)
        with self.assertRaises(AuthenticationError):
            verify_certificate_fingerprint(certificate, None)
        with self.assertRaises(AuthenticationError):
            verify_certificate_fingerprint(certificate, "0" * 64)


class FrameTests(unittest.TestCase):
    def test_round_trip_uses_bounded_metadata_and_payload(self):
        frame = encode_frame({"type": "chunk", "job_id": "abc"}, b"bytes")
        metadata, payload = decode_frame(frame)

        self.assertEqual(metadata["job_id"], "abc")
        self.assertEqual(payload, b"bytes")

    def test_rejects_oversized_or_truncated_frames(self):
        with self.assertRaises(FrameError):
            encode_frame({"type": "chunk"}, b"x" * ((1 << 20) + 1))
        with self.assertRaises(FrameError):
            decode_frame(b"\x00\x00\x00\x10{}")


if __name__ == "__main__":
    unittest.main()
