import os
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import logging
import tempfile
import re
import hashlib
from app.dpapi import protect, unprotect

logger = logging.getLogger(__name__)

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

def pairing_code_from_fingerprint(fingerprint):
    """Return a short, human-readable code derived from a certificate fingerprint.

    The code is only a display aid for the initial pairing check; the complete
    fingerprint remains the value used for cryptographic pinning.
    """
    if not isinstance(fingerprint, str):
        return ""
    compact = re.sub(r"[^0-9a-fA-F]", "", fingerprint)
    if len(compact) < 12:
        return ""
    return "-".join(compact[:12].upper()[i:i + 4] for i in range(0, 12, 4))

# Backwards-compatible short name used by the GUI.
pairing_code = pairing_code_from_fingerprint

def certificate_fingerprint(cert_file=CERT_FILE):
    """Return the SHA-256 fingerprint of the local PEM certificate."""
    from cryptography import x509
    with open(cert_file, "rb") as stream:
        cert = x509.load_pem_x509_certificate(stream.read())
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()

def ensure_certificates():
    """Generates self-signed certificates if they don't exist."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        try:
            with open(CERT_FILE, "rb") as stream:
                certificate = x509.load_pem_x509_certificate(stream.read())
            private_key = serialization.load_pem_private_key(load_private_key_bytes(), password=None)
            if private_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ) == certificate.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ):
                return True
            logger.warning("DeskFlow certificate and private key do not match; regenerating identity")
        except Exception as error:
            logger.warning("DeskFlow identity is unreadable; regenerating identity: %s", error)

    logger.info("Generating new self-signed certificate...")
    try:
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )

        # Generate public certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, u"DeskFlow"),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=3650)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
            critical=False,
        ).sign(private_key, hashes.SHA256())

        # Write private key to file
        write_private_key(private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        # Write certificate to file
        with open(CERT_FILE, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info("Self-signed certificate generated successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to generate certificate: {e}")
        return False

def load_private_key_bytes():
    """Read the DPAPI-protected key, migrating legacy plaintext keys once."""
    with open(KEY_FILE, "rb") as stream:
        raw = stream.read()
    try:
        decoded = unprotect(raw)
        if decoded != raw or os.name == "nt":
            return decoded
    except Exception:
        pass
    if os.name == "nt":
        protected = protect(raw)
        with open(KEY_FILE, "wb") as stream:
            stream.write(protected)
    return raw

def write_private_key(key_bytes):
    with open(KEY_FILE, "wb") as stream:
        stream.write(protect(key_bytes))

def materialize_private_key():
    """Create a short-lived plaintext key path for libraries that require a filename."""
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    handle.write(load_private_key_bytes())
    handle.close()
    try:
        os.chmod(handle.name, 0o600)
    except OSError:
        pass
    return handle.name
