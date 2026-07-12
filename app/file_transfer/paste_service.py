import threading

from .handshake import ManifestHandshakeQueue
from .executor import FifoTransferExecutor


class FilePasteService:
    def __init__(
        self,
        control,
        receiver,
        publisher,
        sender,
        snapshot_selection,
        executor=None,
    ):
        self.control = control
        self.receiver = receiver
        self.publisher = publisher
        self.sender = sender
        self.snapshot_selection = snapshot_selection
        self.executor = executor or FifoTransferExecutor(sender)
        self.handshakes = ManifestHandshakeQueue(self.control.send_message)
        self._outgoing = {}

    def request_paste(self):
        return self.handshakes.begin()

    def on_manifest_request(self, message):
        request_id = message.get("request_id")
        try:
            manifest, sources = self.snapshot_selection()
            self._outgoing[manifest.job_id] = (manifest, sources)
            self.control.send_message({
                "type": "file_manifest_response",
                "request_id": request_id,
                "manifest": manifest.to_wire(),
            })
        except Exception as error:
            self.control.send_message({
                "type": "file_manifest_failed",
                "request_id": request_id,
                "error": type(error).__name__,
            })

    def on_manifest_response(self, message):
        request_id = message.get("request_id")
        manifest = message.get("manifest")
        if not self.handshakes.accept(request_id, manifest):
            return False
        self.receiver.accept_manifest(manifest)
        self.publisher.publish_and_paste(manifest, self.receiver)
        self.control.send_message({
            "type": "file_manifest_ack",
            "job_id": manifest["job_id"],
        })
        return True

    def on_manifest_failed(self, message):
        return self.handshakes.fail(message.get("request_id"), message.get("error", "failed"))

    def on_manifest_ack(self, message):
        outgoing = self._outgoing.pop(message.get("job_id"), None)
        if outgoing is None:
            return False
        manifest, sources = outgoing
        self.executor.submit(manifest, sources)
        return True
