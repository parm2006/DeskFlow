import os
import datetime
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import logging
import tempfile
from app.dpapi import protect, unprotect

logger = logging.getLogger(__name__)

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

def ensure_certificates():
    """Generates self-signed certificates if they don't exist."""
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return True

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
