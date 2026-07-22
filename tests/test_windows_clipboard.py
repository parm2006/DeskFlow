import unittest
from unittest.mock import patch

from app import windows_clipboard
from app.clipboard_formats import ClipboardEntry, ClipboardPayloadError, ClipboardSnapshot
from app.windows_clipboard import (
    ClipboardAccessError,
    GlobalMemoryReader,
    WindowsClipboardAdapter,
)


class FakeClipboardApi:
    CF_UNICODETEXT = 13
    CF_DIB = 8
    CF_DIBV5 = 17

    def __init__(self):
        self.registered = []
        self.registered_ids = {
            "HTML Format": 101,
            "Rich Text Format": 102,
            "PNG": 103,
            "Chromium Web Custom MIME Data Format": 104,
        }
        self.enumerated = []
        self.text = "hello"
        self.fail_registration = None
        self.emptied = 0
        self.set_calls = []
        self.fail_set_format = None
        self.fail_empty = False

    def RegisterClipboardFormat(self, name):
        self.registered.append(name)
        if name == self.fail_registration:
            raise OSError("private operating-system detail")
        return self.registered_ids[name]

    def EnumClipboardFormats(self, previous):
        if not self.enumerated:
            return 0
        if previous == 0:
            return self.enumerated[0]
        index = self.enumerated.index(previous) + 1
        return self.enumerated[index] if index < len(self.enumerated) else 0

    def GetClipboardData(self, format_id):
        if format_id != self.CF_UNICODETEXT:
            raise AssertionError("only Unicode text may use the pywin32 read path")
        return self.text

    def EmptyClipboard(self):
        if self.fail_empty:
            raise OSError("private empty failure")
        self.emptied += 1

    def SetClipboardData(self, format_id, value):
        self.set_calls.append((format_id, value))
        if format_id == self.fail_set_format:
            raise OSError("publication failed")


class FakeMemoryReader:
    def __init__(self, values):
        self.values = values
        self.reads = []

    def read(self, format_id, limit):
        self.reads.append((format_id, limit))
        value = self.values[format_id]
        if isinstance(value, Exception):
            raise value
        if len(value) > limit:
            raise ClipboardPayloadError("clipboard format exceeds its size limit")
        return value


class FakeUser32:
    def __init__(self, handle=41):
        self.handle = handle
        self.requested_formats = []

    def GetClipboardData(self, format_id):
        self.requested_formats.append(format_id)
        return self.handle


class FakeKernel32:
    def __init__(self, size, pointer=99):
        self.size = size
        self.pointer = pointer
        self.locked = []
        self.unlocked = []

    def GlobalSize(self, handle):
        return self.size

    def GlobalLock(self, handle):
        self.locked.append(handle)
        return self.pointer

    def GlobalUnlock(self, handle):
        self.unlocked.append(handle)


class WindowsClipboardRegistryTests(unittest.TestCase):
    def test_registers_only_portable_registered_formats(self):
        api = FakeClipboardApi()

        WindowsClipboardAdapter(api, FakeMemoryReader({}))

        self.assertEqual(
            api.registered,
            [
                "HTML Format",
                "Rich Text Format",
                "PNG",
                "Chromium Web Custom MIME Data Format",
            ],
        )

    def test_captures_and_publishes_bounded_chromium_web_custom_data(self):
        api = FakeClipboardApi()
        format_id = api.registered_ids["Chromium Web Custom MIME Data Format"]
        memory = FakeMemoryReader({format_id: b"docs-object-data"})
        adapter = WindowsClipboardAdapter(api, memory)
        api.enumerated = [format_id]

        snapshot = adapter.capture_open_clipboard()
        adapter.publish_open_clipboard(snapshot)

        self.assertEqual(
            snapshot.entries,
            (ClipboardEntry("chromium_web_custom", b"docs-object-data"),),
        )
        self.assertEqual(api.set_calls, [(format_id, b"docs-object-data")])

    def test_registration_failure_names_only_the_stable_kind(self):
        api = FakeClipboardApi()
        api.fail_registration = "PNG"

        with self.assertRaises(ClipboardAccessError) as raised:
            WindowsClipboardAdapter(api, FakeMemoryReader({}))

        self.assertIn("png", str(raised.exception))
        self.assertNotIn("private operating-system detail", str(raised.exception))

    def test_capture_preserves_allowed_enumeration_order_and_ignores_unknown(self):
        api = FakeClipboardApi()
        memory = FakeMemoryReader(
            {
                api.registered_ids["PNG"]: b"png",
                api.registered_ids["HTML Format"]: b"html",
                api.CF_DIBV5: b"dibv5",
            }
        )
        adapter = WindowsClipboardAdapter(api, memory)
        api.enumerated = [
            api.registered_ids["PNG"],
            999,
            api.registered_ids["HTML Format"],
            api.CF_UNICODETEXT,
            api.CF_DIBV5,
        ]

        snapshot = adapter.capture_open_clipboard()

        self.assertEqual(
            [entry.kind for entry in snapshot.entries],
            ["png", "html", "unicode_text", "dibv5"],
        )
        self.assertEqual(
            [entry.data for entry in snapshot.entries],
            [b"png", b"html", "hello\0".encode("utf-16le"), b"dibv5"],
        )
        self.assertEqual(
            [format_id for format_id, _limit in memory.reads],
            [api.registered_ids["PNG"], api.registered_ids["HTML Format"], api.CF_DIBV5],
        )


class GlobalMemoryReaderTests(unittest.TestCase):
    def test_rejects_global_memory_size_before_locking_or_copying(self):
        user32 = FakeUser32()
        kernel32 = FakeKernel32(size=5)
        copies = []
        reader = GlobalMemoryReader(
            user32,
            kernel32,
            lambda pointer, size: copies.append((pointer, size)),
        )

        with self.assertRaises(ClipboardPayloadError):
            reader.read(103, 4)

        self.assertEqual(kernel32.locked, [])
        self.assertEqual(copies, [])

    def test_unlocks_global_memory_when_copy_fails(self):
        user32 = FakeUser32()
        kernel32 = FakeKernel32(size=4)

        def fail_copy(_pointer, _size):
            raise RuntimeError("copy failed")

        reader = GlobalMemoryReader(user32, kernel32, fail_copy)

        with self.assertRaises(RuntimeError):
            reader.read(103, 4)

        self.assertEqual(kernel32.locked, [user32.handle])
        self.assertEqual(kernel32.unlocked, [user32.handle])


class WindowsClipboardCaptureTests(unittest.TestCase):
    def test_empty_allowlisted_offer_returns_none(self):
        api = FakeClipboardApi()
        api.enumerated = [999]
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))

        self.assertIsNone(adapter.capture_open_clipboard())

    def test_unicode_is_canonicalized_and_malformed_text_is_rejected(self):
        api = FakeClipboardApi()
        api.enumerated = [api.CF_UNICODETEXT]
        api.text = "hello\0\0"
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))

        snapshot = adapter.capture_open_clipboard()

        self.assertEqual(snapshot.entries[0].data, "hello\0".encode("utf-16le"))

        api.text = "\ud800"
        with self.assertRaises(ClipboardPayloadError):
            adapter.capture_open_clipboard()

    def test_oversized_unicode_and_aggregate_capture_are_rejected(self):
        api = FakeClipboardApi()
        api.enumerated = [api.CF_UNICODETEXT]
        api.text = "too long"
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))

        with patch.dict(windows_clipboard.FORMAT_LIMITS, {"unicode_text": 4}):
            with self.assertRaises(ClipboardPayloadError):
                adapter.capture_open_clipboard()

        memory = FakeMemoryReader(
            {
                api.registered_ids["HTML Format"]: b"abc",
                api.registered_ids["Rich Text Format"]: b"def",
            }
        )
        adapter = WindowsClipboardAdapter(api, memory)
        api.enumerated = [
            api.registered_ids["HTML Format"],
            api.registered_ids["Rich Text Format"],
        ]
        with patch.object(windows_clipboard, "MAX_SNAPSHOT_BYTES", 5):
            with self.assertRaises(ClipboardPayloadError):
                adapter.capture_open_clipboard()

    def test_capture_failure_after_valid_entry_does_not_return_partial_snapshot(self):
        api = FakeClipboardApi()
        failure = ClipboardAccessError("read failed")
        memory = FakeMemoryReader(
            {
                api.registered_ids["HTML Format"]: b"html",
                api.registered_ids["PNG"]: failure,
            }
        )
        adapter = WindowsClipboardAdapter(api, memory)
        api.enumerated = [
            api.registered_ids["HTML Format"],
            api.registered_ids["PNG"],
        ]

        with self.assertRaises(ClipboardAccessError):
            adapter.capture_open_clipboard()


class WindowsClipboardPublicationTests(unittest.TestCase):
    def test_publish_validates_then_sets_all_formats_in_source_order(self):
        api = FakeClipboardApi()
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))
        snapshot = ClipboardSnapshot(
            [
                ClipboardEntry("png", b"png"),
                ClipboardEntry("html", b"html"),
                ClipboardEntry("unicode_text", "hello\0".encode("utf-16le")),
                ClipboardEntry("dibv5", b"dibv5"),
                ClipboardEntry("rtf", b"rtf"),
                ClipboardEntry("dib", b"dib"),
            ]
        )

        adapter.publish_open_clipboard(snapshot)

        self.assertEqual(api.emptied, 1)
        self.assertEqual(
            api.set_calls,
            [
                (api.registered_ids["PNG"], b"png"),
                (api.registered_ids["HTML Format"], b"html"),
                (api.CF_UNICODETEXT, "hello"),
                (api.CF_DIBV5, b"dibv5"),
                (api.registered_ids["Rich Text Format"], b"rtf"),
                (api.CF_DIB, b"dib"),
            ],
        )

    def test_malformed_unicode_is_rejected_before_emptying_clipboard(self):
        api = FakeClipboardApi()
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))

        for malformed in (b"odd", b"missing terminator", b"\x00\xd8\x00\x00"):
            with self.subTest(malformed=malformed):
                snapshot = ClipboardSnapshot(
                    [ClipboardEntry("unicode_text", malformed)]
                )
                with self.assertRaises(ClipboardPayloadError):
                    adapter.publish_open_clipboard(snapshot)

        self.assertEqual(api.emptied, 0)
        self.assertEqual(api.set_calls, [])

    def test_mid_publication_failure_stops_without_retrying(self):
        api = FakeClipboardApi()
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))
        api.fail_set_format = api.registered_ids["HTML Format"]
        snapshot = ClipboardSnapshot(
            [
                ClipboardEntry("png", b"png"),
                ClipboardEntry("html", b"html"),
                ClipboardEntry("dib", b"dib"),
            ]
        )

        with self.assertRaises(ClipboardAccessError) as raised:
            adapter.publish_open_clipboard(snapshot)

        self.assertNotIn("publication failed", str(raised.exception))
        self.assertEqual(api.emptied, 1)
        self.assertEqual(
            api.set_calls,
            [
                (api.registered_ids["PNG"], b"png"),
                (api.registered_ids["HTML Format"], b"html"),
            ],
        )

    def test_empty_failure_is_reported_as_safe_adapter_error(self):
        api = FakeClipboardApi()
        api.fail_empty = True
        adapter = WindowsClipboardAdapter(api, FakeMemoryReader({}))
        snapshot = ClipboardSnapshot([ClipboardEntry("html", b"html")])

        with self.assertRaises(ClipboardAccessError) as raised:
            adapter.publish_open_clipboard(snapshot)

        self.assertNotIn("private empty failure", str(raised.exception))
        self.assertEqual(api.set_calls, [])

    def test_default_adapter_uses_system_clipboard_and_memory_reader(self):
        api = FakeClipboardApi()
        memory = FakeMemoryReader({})

        with patch.object(windows_clipboard, "win32clipboard", api), patch.object(
            GlobalMemoryReader, "from_system", return_value=memory
        ) as from_system:
            adapter = WindowsClipboardAdapter()

        self.assertIs(adapter._clipboard, api)
        self.assertIs(adapter._memory, memory)
        from_system.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
