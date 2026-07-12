import struct
import unittest
import tempfile
import gc
from pathlib import Path

import pythoncom
from win32com.server import util

from app.windows_virtual_files import (
    FILEDESCRIPTORW_SIZE,
    VirtualFile,
    VirtualFileDataObject,
    VirtualFileSet,
    build_file_group_descriptor,
    parse_file_group_descriptor,
    open_file_stream,
    open_callback_stream,
)


class FileGroupDescriptorTests(unittest.TestCase):
    def test_builds_unicode_descriptors_with_size_and_attributes(self):
        files = [
            VirtualFile("notes.txt", 5, lambda: b"hello"),
            VirtualFile("資料/report.csv", 4, lambda: b"a,b\n"),
        ]

        packed = build_file_group_descriptor(files)
        parsed = parse_file_group_descriptor(packed)

        self.assertEqual(struct.unpack_from("<I", packed)[0], 2)
        self.assertEqual(len(packed), 4 + (2 * FILEDESCRIPTORW_SIZE))
        self.assertEqual(
            [(item.name, item.size, item.is_directory) for item in parsed],
            [("notes.txt", 5, False), ("資料/report.csv", 4, False)],
        )

    def test_rejects_names_that_do_not_fit_windows_descriptor(self):
        with self.assertRaisesRegex(ValueError, "259 characters"):
            VirtualFile("x" * 260, 0, lambda: b"")

    def test_directory_descriptor_has_no_file_contents(self):
        files = [VirtualFile("folder", 0, None, is_directory=True)]
        file_set = VirtualFileSet(files)

        descriptor = parse_file_group_descriptor(file_set.descriptor_bytes())[0]

        self.assertTrue(descriptor.is_directory)
        with self.assertRaisesRegex(ValueError, "directory"):
            file_set.content_bytes(0)


class VirtualFileSetTests(unittest.TestCase):
    def test_returns_content_by_descriptor_index(self):
        file_set = VirtualFileSet(
            [
                VirtualFile("first.txt", 3, lambda: b"one"),
                VirtualFile("second.txt", 3, lambda: b"two"),
            ]
        )

        self.assertEqual(file_set.content_bytes(0), b"one")
        self.assertEqual(file_set.content_bytes(1), b"two")

    def test_rejects_content_whose_size_changed(self):
        file_set = VirtualFileSet([VirtualFile("changed.txt", 3, lambda: b"longer")])

        with self.assertRaisesRegex(ValueError, "expected 3 bytes"):
            file_set.content_bytes(0)

    def test_rejects_invalid_stream_index(self):
        file_set = VirtualFileSet([VirtualFile("one.txt", 1, lambda: b"1")])

        with self.assertRaises(IndexError):
            file_set.content_bytes(1)


class VirtualFileDataObjectTests(unittest.TestCase):
    def setUp(self):
        pythoncom.OleInitialize()
        self.addCleanup(pythoncom.CoUninitialize)
        self.file_set = VirtualFileSet(
            [
                VirtualFile("first.txt", 3, lambda: b"one"),
                VirtualFile("second.txt", 3, lambda: b"two"),
            ]
        )
        self.data_object = VirtualFileDataObject(self.file_set)

    def test_com_gateway_returns_descriptor_hglobal(self):
        wrapped = util.wrap(self.data_object, pythoncom.IID_IDataObject)
        format_etc = self.data_object.descriptor_format_etc()

        wrapped.QueryGetData(format_etc)
        medium = wrapped.GetData(format_etc)

        self.assertEqual(medium.tymed, pythoncom.TYMED_HGLOBAL)
        self.assertEqual(parse_file_group_descriptor(medium.data)[-1].name, "second.txt")

    def test_com_gateway_returns_indexed_content_stream(self):
        wrapped = util.wrap(self.data_object, pythoncom.IID_IDataObject)

        medium = wrapped.GetData(self.data_object.content_format_etc(1))

        self.assertEqual(medium.tymed, pythoncom.TYMED_ISTREAM)
        self.assertEqual(medium.data.Read(3), b"two")

    def test_com_gateway_enumerates_descriptor_and_contents_formats(self):
        wrapped = util.wrap(self.data_object, pythoncom.IID_IDataObject)

        formats = wrapped.EnumFormatEtc(pythoncom.DATADIR_GET).Next(10)

        self.assertEqual(formats[0], self.data_object.descriptor_format_etc())
        self.assertEqual(formats[1], self.data_object.content_format_etc(0))
        self.assertEqual(formats[2], self.data_object.content_format_etc(1))

    def test_com_gateway_streams_file_without_loading_content_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.bin"
            path.write_bytes(b"0123456789")
            file_set = VirtualFileSet([
                VirtualFile(
                    "large.bin",
                    10,
                    None,
                    open_stream=lambda: open_file_stream(path, 10),
                )
            ])
            data_object = VirtualFileDataObject(file_set)
            wrapped = util.wrap(data_object, pythoncom.IID_IDataObject)

            stream = wrapped.GetData(data_object.content_format_etc(0)).data

            self.assertEqual(stream.Read(4), b"0123")
            stream.Seek(2, 0)
            self.assertEqual(stream.Read(3), b"234")
            del stream, wrapped, data_object
            gc.collect()

    def test_com_gateway_reads_from_growing_callback_stream(self):
        content = b"growing bytes"
        reads = []

        def read_range(offset, count):
            reads.append((offset, count))
            return content[offset:offset + count]

        file_set = VirtualFileSet([
            VirtualFile(
                "remote.bin",
                len(content),
                None,
                open_stream=lambda: open_callback_stream(read_range, len(content)),
            )
        ])
        data_object = VirtualFileDataObject(file_set)
        wrapped = util.wrap(data_object, pythoncom.IID_IDataObject)
        stream = wrapped.GetData(data_object.content_format_etc(0)).data

        self.assertEqual(stream.Read(7), b"growing")
        self.assertEqual(stream.Read(6), b" bytes")
        self.assertEqual(reads, [(0, 7), (7, 6)])


if __name__ == "__main__":
    unittest.main()
