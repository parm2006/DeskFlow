import ctypes
from ctypes import wintypes

import win32clipboard

from app.clipboard_formats import (
    ClipboardEntry,
    ClipboardPayloadError,
    ClipboardSnapshot,
    FORMAT_LIMITS,
    MAX_SNAPSHOT_BYTES,
)


class ClipboardAccessError(RuntimeError):
    pass


class GlobalMemoryReader:
    def __init__(self, user32, kernel32, copy_bytes=ctypes.string_at):
        self._user32 = user32
        self._kernel32 = kernel32
        self._copy_bytes = copy_bytes

    @classmethod
    def from_system(cls):
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalSize.argtypes = [wintypes.HANDLE]
        kernel32.GlobalSize.restype = ctypes.c_size_t
        kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        return cls(user32, kernel32)

    def read(self, format_id, limit):
        handle = self._user32.GetClipboardData(format_id)
        if not handle:
            raise ClipboardAccessError("could not access clipboard format data")
        size = self._kernel32.GlobalSize(handle)
        if size > limit:
            raise ClipboardPayloadError("clipboard format exceeds its size limit")
        if size == 0:
            return b""
        pointer = self._kernel32.GlobalLock(handle)
        if not pointer:
            raise ClipboardAccessError("could not lock clipboard format data")
        try:
            return self._copy_bytes(pointer, size)
        finally:
            self._kernel32.GlobalUnlock(handle)


class WindowsClipboardAdapter:
    def __init__(self, clipboard_api=None, memory_reader=None):
        if clipboard_api is None:
            clipboard_api = win32clipboard
        if memory_reader is None:
            memory_reader = GlobalMemoryReader.from_system()
        self._clipboard = clipboard_api
        self._memory = memory_reader
        registered = {}
        for kind, name in (
            ("html", "HTML Format"),
            ("rtf", "Rich Text Format"),
            ("png", "PNG"),
            (
                "chromium_web_custom",
                "Chromium Web Custom MIME Data Format",
            ),
        ):
            try:
                registered[kind] = clipboard_api.RegisterClipboardFormat(name)
            except Exception as error:
                raise ClipboardAccessError(
                    f"could not register clipboard format {kind}"
                ) from error
        self._id_to_kind = {
            clipboard_api.CF_UNICODETEXT: "unicode_text",
            registered["html"]: "html",
            registered["rtf"]: "rtf",
            registered["png"]: "png",
            registered["chromium_web_custom"]: "chromium_web_custom",
            clipboard_api.CF_DIB: "dib",
            clipboard_api.CF_DIBV5: "dibv5",
        }
        self._kind_to_id = {
            kind: format_id for format_id, kind in self._id_to_kind.items()
        }

    def capture_open_clipboard(self):
        entries = []
        previous = 0
        total = 0
        while True:
            format_id = self._clipboard.EnumClipboardFormats(previous)
            if not format_id:
                break
            previous = format_id
            kind = self._id_to_kind.get(format_id)
            if kind is None:
                continue
            remaining = MAX_SNAPSHOT_BYTES - total
            if kind == "unicode_text":
                text = self._clipboard.GetClipboardData(format_id)
                if not isinstance(text, str):
                    raise ClipboardPayloadError(
                        "clipboard format unicode_text data must be text"
                    )
                try:
                    data = (text.rstrip("\0") + "\0").encode("utf-16le")
                except UnicodeEncodeError as error:
                    raise ClipboardPayloadError(
                        "clipboard format unicode_text data is invalid"
                    ) from error
            else:
                data = self._memory.read(
                    format_id,
                    min(FORMAT_LIMITS[kind], remaining),
                )
            entry = ClipboardEntry(kind, data)
            entries.append(entry)
            total += len(data)
            if total > MAX_SNAPSHOT_BYTES:
                raise ClipboardPayloadError(
                    "clipboard snapshot exceeds its size limit"
                )
        return ClipboardSnapshot(entries) if entries else None

    def publish_open_clipboard(self, snapshot):
        if not isinstance(snapshot, ClipboardSnapshot):
            raise ClipboardPayloadError("clipboard value must be a snapshot")
        snapshot = ClipboardSnapshot(snapshot.entries)
        prepared = []
        for entry in snapshot.entries:
            value = entry.data
            if entry.kind == "unicode_text":
                if len(value) < 2 or len(value) % 2 or not value.endswith(b"\0\0"):
                    raise ClipboardPayloadError(
                        "clipboard format unicode_text data is invalid"
                    )
                try:
                    value = value[:-2].decode("utf-16le")
                except UnicodeDecodeError as error:
                    raise ClipboardPayloadError(
                        "clipboard format unicode_text data is invalid"
                    ) from error
                if "\0" in value:
                    raise ClipboardPayloadError(
                        "clipboard format unicode_text data is invalid"
                    )
            prepared.append((self._kind_to_id[entry.kind], value))

        try:
            self._clipboard.EmptyClipboard()
            for format_id, value in prepared:
                self._clipboard.SetClipboardData(format_id, value)
        except Exception as error:
            raise ClipboardAccessError(
                "could not publish clipboard snapshot"
            ) from error
