import zlib
from dataclasses import dataclass
from pathlib import PurePath


MIN_COMPRESS_SIZE = 1 << 20
MAX_CHUNK_SIZE = 1 << 20
MIN_SAVINGS_RATIO = 0.12
_COMPRESSED_SUFFIXES = {
    ".7z", ".avi", ".bz2", ".docx", ".gz", ".jpeg", ".jpg", ".m4a", ".mkv",
    ".mov", ".mp3", ".mp4", ".pdf", ".png", ".pptx", ".rar", ".webm", ".webp",
    ".xlsx", ".xz", ".zip",
}


class CompressionError(ValueError):
    pass


@dataclass(frozen=True)
class EncodedChunk:
    data: bytes
    compressed: bool
    original_size: int


def should_compress(filename, file_size, sample):
    if file_size < MIN_COMPRESS_SIZE:
        return False
    if PurePath(filename).suffix.lower() in _COMPRESSED_SUFFIXES:
        return False
    if not sample:
        return False
    compressed_size = len(zlib.compress(sample, level=1))
    return compressed_size <= len(sample) * (1 - MIN_SAVINGS_RATIO)


def encode_chunk(data, compress):
    if not isinstance(data, bytes):
        raise TypeError("chunk data must be bytes")
    if len(data) > MAX_CHUNK_SIZE:
        raise CompressionError("chunk exceeds the 1 MiB limit")
    encoded = zlib.compress(data, level=1) if compress else data
    return EncodedChunk(encoded, compress, len(data))


def decode_chunk(data, compressed, expected_size):
    if expected_size < 0 or expected_size > MAX_CHUNK_SIZE:
        raise CompressionError("declared output size is outside the chunk limit")
    if not compressed:
        if len(data) != expected_size:
            raise CompressionError("raw chunk size does not match its declaration")
        return data

    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(data, expected_size + 1)
    except zlib.error as error:
        raise CompressionError("compressed chunk is invalid") from error
    if len(decoded) != expected_size or not decoder.eof or decoder.unconsumed_tail or decoder.unused_data:
        raise CompressionError("compressed chunk exceeds or does not match its declared size")
    return decoded
