import queue
import threading
import time

import pythoncom
from pynput.keyboard import Controller as KeyboardController, Key

from app.windows_virtual_files import (
    VirtualFile,
    VirtualFileSet,
    open_callback_stream,
    publish_virtual_files,
)


def build_virtual_file_set(manifest, receiver):
    job_id = manifest["job_id"]
    files = []
    for item in manifest["items"]:
        relative_path = item["relative_path"]
        if item["item_type"] == "directory":
            files.append(VirtualFile(relative_path, 0, None, is_directory=True))
            continue

        size = item["size"]

        def open_stream(path=relative_path, stream_size=size):
            return open_callback_stream(
                lambda offset, count: receiver.read_range(
                    job_id, path, offset, count
                ),
                stream_size,
                on_read=lambda offset, count, path=path: receiver.record_stream_read(
                    job_id, path, offset, count
                ),
            )

        files.append(VirtualFile(relative_path, size, None, open_stream=open_stream))
    return VirtualFileSet(files)


class VirtualPastePublisher:
    def __init__(self):
        self._queue = queue.Queue()
        self._thread = None
        self._owners = []

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def publish_and_paste(self, manifest, receiver):
        self.start()
        self._queue.put((manifest, receiver))

    def _worker(self):
        pythoncom.OleInitialize()
        keyboard = KeyboardController()
        try:
            while True:
                try:
                    manifest, receiver = self._queue.get(timeout=0.01)
                except queue.Empty:
                    pythoncom.PumpWaitingMessages()
                    continue
                file_set = build_virtual_file_set(manifest, receiver)
                self._owners.append(publish_virtual_files(file_set))
                keyboard.press(Key.ctrl)
                keyboard.press("v")
                keyboard.release("v")
                keyboard.release(Key.ctrl)
                deadline = time.monotonic() + 0.15
                while time.monotonic() < deadline:
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.005)
        finally:
            pythoncom.CoUninitialize()
