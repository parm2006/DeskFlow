from .compression import encode_chunk, should_compress
from .models import ItemType
from .validation import validate_manifest


class TransferSender:
    def __init__(self, lane):
        self.lane = lane

    def send_job(self, manifest, sources, announce_manifest=True):
        validate_manifest(manifest)
        if announce_manifest:
            self.lane.send({"type": "manifest", "manifest": manifest.to_wire()})
        for item in manifest.items:
            if item.item_type is ItemType.DIRECTORY:
                continue
            source = sources[item.relative_path]
            if source.size != item.size or source.sha256 != item.sha256:
                raise ValueError("source snapshot does not match the manifest")
            chunks = iter(source.iter_chunks())
            first = next(chunks, None)
            compress = bool(first) and should_compress(item.relative_path, item.size, first)
            offset = 0
            for chunk in (() if first is None else (first,)):
                offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
            for chunk in chunks:
                offset = self._send_chunk(manifest.job_id, item.relative_path, offset, chunk, compress)
            self.lane.send({
                "type": "file_complete",
                "job_id": manifest.job_id,
                "relative_path": item.relative_path,
            })

    def _send_chunk(self, job_id, relative_path, offset, chunk, compress):
        encoded = encode_chunk(chunk, compress)
        self.lane.send(
            {
                "type": "chunk",
                "job_id": job_id,
                "relative_path": relative_path,
                "offset": offset,
                "compressed": encoded.compressed,
                "original_size": encoded.original_size,
            },
            encoded.data,
        )
        return offset + len(chunk)
