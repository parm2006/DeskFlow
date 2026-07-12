import hashlib
import os
import secrets
from pathlib import Path

from .validation import ValidationError, validate_relative_path


class IntegrityError(ValueError):
    pass


class StagedFile:
    def __init__(self, root, job_id, relative_path, expected_size, expected_sha256):
        if not isinstance(job_id, str) or not job_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in job_id):
            raise ValidationError("job ID contains unsafe characters")
        if expected_size < 0:
            raise ValidationError("expected size cannot be negative")
        if len(expected_sha256) != 64 or any(character not in "0123456789abcdef" for character in expected_sha256.lower()):
            raise ValidationError("expected SHA-256 must contain 64 hexadecimal characters")

        self.root = Path(root).resolve()
        self.job_id = job_id
        self.relative_path = validate_relative_path(relative_path)
        self.expected_size = expected_size
        self.expected_sha256 = expected_sha256.lower()
        partial_dir = self.root / "partial" / job_id
        partial_dir.mkdir(parents=True, exist_ok=True)
        self.partial_path = partial_dir / f"{secrets.token_hex(16)}.partial"
        self._file = self.partial_path.open("xb")
        self._offset = 0
        self._hash = hashlib.sha256()

    def write(self, offset, data):
        if self._file.closed:
            raise ValueError("staged file is closed")
        if offset != self._offset:
            raise ValueError(f"chunk offset {offset} does not match expected offset {self._offset}")
        if not isinstance(data, bytes):
            raise TypeError("chunk data must be bytes")
        if self._offset + len(data) > self.expected_size:
            raise ValueError("chunk exceeds the declared size")
        self._file.write(data)
        self._hash.update(data)
        self._offset += len(data)

    @property
    def received_size(self):
        return self._offset

    def read_available(self, offset, count):
        self._file.flush()
        with self.partial_path.open("rb") as source:
            source.seek(offset)
            return source.read(min(count, self._offset - offset))

    def finalize(self):
        if self._offset != self.expected_size:
            self.abort()
            raise IntegrityError("received size does not match the declared size")
        if self._hash.hexdigest() != self.expected_sha256:
            self.abort()
            raise IntegrityError("received SHA-256 does not match the manifest")

        self._file.flush()
        os.fsync(self._file.fileno())
        self._file.close()
        destination = self.root / "completed" / self.job_id / Path(*self.relative_path.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(self.partial_path, destination)
        self.partial_path.unlink()
        return destination

    def abort(self):
        if not self._file.closed:
            self._file.close()
        self.partial_path.unlink(missing_ok=True)
