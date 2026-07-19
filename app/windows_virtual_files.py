import struct
import ctypes
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Optional
from ctypes import POINTER, byref, c_void_p
from ctypes.wintypes import BOOL, DWORD

import pythoncom
import win32clipboard
import winerror
from comtypes import (
    COMObject, COMMETHOD, GUID, HRESULT, IUnknown, ReturnHRESULT,
)
from win32com.server import util
from win32com.server.exception import COMException


MAX_DESCRIPTOR_NAME = 259
FILEDESCRIPTORW_SIZE = 592

FD_ATTRIBUTES = 0x00000004
FD_WRITESTIME = 0x00000020
FD_FILESIZE = 0x00000040
FD_PROGRESSUI = 0x00004000
FD_UNICODE = 0x80000000

FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_NORMAL = 0x00000080

FILE_GROUP_DESCRIPTOR_FORMAT = "FileGroupDescriptorW"
FILE_CONTENTS_FORMAT = "FileContents"

IID_IDATAOBJECT_ASYNC_CAPABILITY = GUID(
    "{3D8B0590-F691-11D2-8EA9-006097DF5BD4}"
)


class _IDataObject(IUnknown):
    _iid_ = GUID("{0000010E-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD(
            [], HRESULT, "GetData",
            (["in"], c_void_p, "format"),
            (["in"], c_void_p, "medium"),
        ),
        COMMETHOD(
            [], HRESULT, "GetDataHere",
            (["in"], c_void_p, "format"),
            (["in"], c_void_p, "medium"),
        ),
        COMMETHOD([], HRESULT, "QueryGetData", (["in"], c_void_p, "format")),
        COMMETHOD(
            [], HRESULT, "GetCanonicalFormatEtc",
            (["in"], c_void_p, "source"),
            (["in"], c_void_p, "target"),
        ),
        COMMETHOD(
            [], HRESULT, "SetData",
            (["in"], c_void_p, "format"),
            (["in"], c_void_p, "medium"),
            (["in"], BOOL, "release"),
        ),
        COMMETHOD(
            [], HRESULT, "EnumFormatEtc",
            (["in"], DWORD, "direction"),
            (["in"], c_void_p, "result"),
        ),
        COMMETHOD(
            [], HRESULT, "DAdvise",
            (["in"], c_void_p, "format"),
            (["in"], DWORD, "flags"),
            (["in"], c_void_p, "sink"),
            (["in"], c_void_p, "connection"),
        ),
        COMMETHOD([], HRESULT, "DUnadvise", (["in"], DWORD, "connection")),
        COMMETHOD([], HRESULT, "EnumDAdvise", (["in"], c_void_p, "result")),
    ]


class _IDataObjectAsyncCapability(IUnknown):
    _iid_ = IID_IDATAOBJECT_ASYNC_CAPABILITY
    _methods_ = [
        COMMETHOD([], HRESULT, "SetAsyncMode", (["in"], BOOL, "enabled")),
        COMMETHOD([], HRESULT, "GetAsyncMode", (["in"], c_void_p, "enabled")),
        COMMETHOD([], HRESULT, "StartOperation", (["in"], c_void_p, "reserved")),
        COMMETHOD([], HRESULT, "InOperation", (["in"], c_void_p, "active")),
        COMMETHOD(
            [], HRESULT, "EndOperation",
            (["in"], HRESULT, "result"),
            (["in"], c_void_p, "reserved"),
            (["in"], DWORD, "effects"),
        ),
    ]


_DATA_OBJECT_ARGUMENTS = (
    (c_void_p, c_void_p),
    (c_void_p, c_void_p),
    (c_void_p,),
    (c_void_p, c_void_p),
    (c_void_p, c_void_p, BOOL),
    (DWORD, c_void_p),
    (c_void_p, DWORD, c_void_p, c_void_p),
    (DWORD,),
    (c_void_p,),
)


def _pyiunknown_address(value):
    # pywin32 does not expose the native pointer publicly. PyIUnknown stores it
    # immediately after the CPython PyObject header; accept only the exact
    # gateway type constructed above before reading that private field.
    if sys.implementation.name != "cpython" or type(value).__name__ != "PyIDataObject":
        raise TypeError("expected a CPython pywin32 IDataObject gateway")
    address = c_void_p.from_address(
        id(value) + (2 * ctypes.sizeof(c_void_p))
    ).value
    if not address:
        raise RuntimeError("COM data object has no native interface")
    pythoncom.ObjectFromAddress(address, pythoncom.IID_IUnknown)
    return address


class _AsyncDataObjectProxy(COMObject):
    _com_interfaces_ = [_IDataObject, _IDataObjectAsyncCapability]

    def __init__(self, inner, on_operation_end=None):
        super().__init__()
        self._inner_owner = inner
        self._on_operation_end = on_operation_end
        self._inner = _pyiunknown_address(inner)
        self._vtable = ctypes.cast(
            self._inner, POINTER(POINTER(c_void_p))
        ).contents
        self._async_mode = True
        self._in_operation = False
        self._async_hold = None
        self._state_lock = threading.Lock()

    def _forward(self, index, *arguments):
        prototype = ctypes.WINFUNCTYPE(
            ctypes.c_long, c_void_p, *_DATA_OBJECT_ARGUMENTS[index - 3]
        )
        result = prototype(self._vtable[index])(
            self._inner, *arguments
        )
        if result:
            raise ReturnHRESULT(result, "")
        return 0

    def GetData(self, format_pointer, medium_pointer):
        return self._forward(3, format_pointer, medium_pointer)

    def GetDataHere(self, format_pointer, medium_pointer):
        return self._forward(4, format_pointer, medium_pointer)

    def QueryGetData(self, format_pointer):
        return self._forward(5, format_pointer)

    def GetCanonicalFormatEtc(self, source, target):
        return self._forward(6, source, target)

    def SetData(self, format_pointer, medium_pointer, release):
        return self._forward(7, format_pointer, medium_pointer, release)

    def EnumFormatEtc(self, direction, result):
        return self._forward(8, direction, result)

    def DAdvise(self, format_pointer, flags, sink, connection):
        return self._forward(9, format_pointer, flags, sink, connection)

    def DUnadvise(self, connection):
        return self._forward(10, connection)

    def EnumDAdvise(self, result):
        return self._forward(11, result)

    def SetAsyncMode(self, enabled):
        release = None
        with self._state_lock:
            self._async_mode = bool(enabled)
            if self._async_mode and self._async_hold is None:
                self._async_hold = self.QueryInterface(
                    _IDataObjectAsyncCapability
                )
            elif not self._async_mode:
                release, self._async_hold = self._async_hold, None
        del release
        return 0

    def GetAsyncMode(self, enabled):
        with self._state_lock:
            value = self._async_mode
        ctypes.cast(enabled, POINTER(BOOL))[0] = value
        return 0

    def StartOperation(self, reserved):
        with self._state_lock:
            self._in_operation = True
        return 0

    def InOperation(self, active):
        with self._state_lock:
            value = self._in_operation
        ctypes.cast(active, POINTER(BOOL))[0] = value
        return 0

    def EndOperation(self, result, reserved, effects):
        with self._state_lock:
            self._in_operation = False
            release, self._async_hold = self._async_hold, None
            callback = self._on_operation_end
        if callback is not None:
            callback(int(result), int(effects))
        del release
        return 0


class AsyncClipboardOwner:
    def __init__(self, data_object, wrapped, on_operation_end=None):
        self.data_object = data_object
        self.wrapped = wrapped
        self.proxy = _AsyncDataObjectProxy(
            wrapped, on_operation_end=on_operation_end
        )
        self.data_interface = self.proxy.QueryInterface(_IDataObject)
        self.async_interface = self.data_interface.QueryInterface(
            _IDataObjectAsyncCapability
        )
        self.async_interface.SetAsyncMode(True)
        address = ctypes.cast(self.data_interface, c_void_p).value
        self.clipboard_interface = pythoncom.ObjectFromAddress(
            address, pythoncom.IID_IDataObject
        )

    def async_mode_enabled(self):
        enabled = BOOL()
        self.async_interface.GetAsyncMode(byref(enabled))
        return bool(enabled.value)


@dataclass(frozen=True)
class VirtualFile:
    name: str
    size: int
    read: Optional[Callable[[], bytes]]
    is_directory: bool = False
    modified_filetime: int = 0
    open_stream: Optional[Callable[[], object]] = None

    def __post_init__(self):
        if not self.name or len(self.name) > MAX_DESCRIPTOR_NAME:
            raise ValueError("virtual file names must contain 1 to 259 characters")
        if self.size < 0:
            raise ValueError("virtual file size cannot be negative")
        if self.is_directory and self.read is not None:
            raise ValueError("a directory cannot provide file contents")
        if not self.is_directory and self.read is None and self.open_stream is None:
            raise ValueError("a file must provide file contents")
        if self.read is not None and self.open_stream is not None:
            raise ValueError("a file must provide either bytes or a stream, not both")


@dataclass(frozen=True)
class ParsedFileDescriptor:
    name: str
    size: int
    is_directory: bool


class VirtualFileSet:
    def __init__(self, files: Iterable[VirtualFile]):
        self.files = tuple(files)
        if not self.files:
            raise ValueError("at least one virtual file is required")

    def descriptor_bytes(self):
        return build_file_group_descriptor(self.files)

    def content_bytes(self, index):
        try:
            item = self.files[index]
        except IndexError:
            raise IndexError("virtual file stream index is out of range") from None
        if item.is_directory:
            raise ValueError("a directory has no file contents stream")
        content = item.read()
        if not isinstance(content, bytes):
            raise TypeError("virtual file content provider must return bytes")
        if len(content) != item.size:
            raise ValueError(
                f"virtual file content expected {item.size} bytes, got {len(content)}"
            )
        return content

    def content_stream(self, index):
        try:
            item = self.files[index]
        except IndexError:
            raise IndexError("virtual file stream index is out of range") from None
        if item.is_directory:
            raise ValueError("a directory has no file contents stream")
        if item.open_stream is not None:
            return item.open_stream()
        content = self.content_bytes(index)
        stream = pythoncom.CreateStreamOnHGlobal()
        stream.Write(content)
        stream.Seek(0, 0)
        return stream


class VirtualFileDataObject:
    _com_interfaces_ = [pythoncom.IID_IDataObject]
    _public_methods_ = [
        "GetData",
        "GetDataHere",
        "QueryGetData",
        "GetCanonicalFormatEtc",
        "SetData",
        "EnumFormatEtc",
        "DAdvise",
        "DUnadvise",
        "EnumDAdvise",
    ]

    def __init__(self, file_set, on_performed_drop=None):
        self.file_set = file_set
        self.on_performed_drop = on_performed_drop
        self.descriptor_format = win32clipboard.RegisterClipboardFormat(
            FILE_GROUP_DESCRIPTOR_FORMAT
        )
        self.contents_format = win32clipboard.RegisterClipboardFormat(FILE_CONTENTS_FORMAT)
        self.performed_drop_format = win32clipboard.RegisterClipboardFormat(
            "Performed DropEffect"
        )

    def descriptor_format_etc(self):
        return (
            self.descriptor_format,
            None,
            pythoncom.DVASPECT_CONTENT,
            -1,
            pythoncom.TYMED_HGLOBAL,
        )

    def content_format_etc(self, index):
        return (
            self.contents_format,
            None,
            pythoncom.DVASPECT_CONTENT,
            index,
            pythoncom.TYMED_ISTREAM,
        )

    def QueryGetData(self, format_etc):
        self._validate_format(format_etc)

    def GetData(self, format_etc):
        kind, index = self._validate_format(format_etc)
        medium = pythoncom.STGMEDIUM()
        if kind == "descriptor":
            medium.set(pythoncom.TYMED_HGLOBAL, self.file_set.descriptor_bytes())
            return medium

        stream = self.file_set.content_stream(index)
        medium.set(pythoncom.TYMED_ISTREAM, stream)
        return medium

    def GetDataHere(self, format_etc):
        raise COMException(description="GetDataHere is not supported", scode=winerror.E_NOTIMPL)

    def GetCanonicalFormatEtc(self, format_etc):
        raise COMException(
            description="the requested format is already canonical",
            scode=winerror.DATA_S_SAMEFORMATETC,
        )

    def SetData(self, format_etc, medium, release):
        clipboard_format, target, aspect, index, medium_type = format_etc
        if (
            clipboard_format == self.performed_drop_format
            and target is None
            and aspect == pythoncom.DVASPECT_CONTENT
            and index == -1
            and medium_type & pythoncom.TYMED_HGLOBAL
        ):
            if self.on_performed_drop is not None:
                self.on_performed_drop()
            return None
        raise COMException(description="SetData is not supported", scode=winerror.E_NOTIMPL)

    def EnumFormatEtc(self, direction):
        if direction != pythoncom.DATADIR_GET:
            raise COMException(
                description="only readable formats are supported",
                scode=winerror.E_NOTIMPL,
            )
        formats = [self.descriptor_format_etc()]
        formats.extend(
            self.content_format_etc(index)
            for index, item in enumerate(self.file_set.files)
            if not item.is_directory
        )
        return util.NewEnum(formats, iid=pythoncom.IID_IEnumFORMATETC)

    def DAdvise(self, format_etc, flags, sink):
        raise COMException(description="advises are unsupported", scode=winerror.OLE_E_ADVISENOTSUPPORTED)

    def DUnadvise(self, connection):
        raise COMException(description="advises are unsupported", scode=winerror.OLE_E_ADVISENOTSUPPORTED)

    def EnumDAdvise(self):
        raise COMException(description="advises are unsupported", scode=winerror.OLE_E_ADVISENOTSUPPORTED)

    def _validate_format(self, format_etc):
        clipboard_format, target, aspect, index, medium = format_etc
        if target is not None or aspect != pythoncom.DVASPECT_CONTENT:
            raise COMException(description="unsupported format", scode=winerror.DV_E_FORMATETC)
        if clipboard_format == self.descriptor_format:
            if index != -1 or not medium & pythoncom.TYMED_HGLOBAL:
                raise COMException(description="invalid descriptor format", scode=winerror.DV_E_FORMATETC)
            return "descriptor", -1
        if clipboard_format == self.contents_format:
            if index < 0 or index >= len(self.file_set.files):
                raise COMException(description="invalid file index", scode=winerror.DV_E_LINDEX)
            if self.file_set.files[index].is_directory:
                raise COMException(description="directory has no stream", scode=winerror.DV_E_LINDEX)
            if not medium & pythoncom.TYMED_ISTREAM:
                raise COMException(description="FileContents requires IStream", scode=winerror.DV_E_TYMED)
            return "contents", index
        raise COMException(description="unsupported clipboard format", scode=winerror.DV_E_FORMATETC)


def publish_virtual_files(
    file_set, on_performed_drop=None, on_operation_end=None,
):
    """Publish virtual files through the OLE clipboard on the calling STA thread."""
    data_object = VirtualFileDataObject(
        file_set, on_performed_drop=on_performed_drop
    )
    wrapped = util.wrap(data_object, pythoncom.IID_IDataObject)
    owner = AsyncClipboardOwner(
        data_object, wrapped, on_operation_end=on_operation_end
    )
    pythoncom.OleSetClipboard(owner.clipboard_interface)
    return owner


class FileBackedStream:
    _com_interfaces_ = [pythoncom.IID_IStream]
    _public_methods_ = [
        "Read", "Write", "Seek", "SetSize", "CopyTo", "Commit", "Revert",
        "LockRegion", "UnlockRegion", "Stat", "Clone",
    ]

    def __init__(self, path, size, position=0):
        self.path = str(path)
        self.size = size
        self.file = open(self.path, "rb")
        self.file.seek(position)

    def __del__(self):
        file = getattr(self, "file", None)
        if file is not None:
            file.close()

    def Read(self, count):
        return self.file.read(min(count, self.size - self.file.tell()))

    def Write(self, data):
        raise COMException(description="stream is read-only", scode=winerror.STG_E_ACCESSDENIED)

    def Seek(self, offset, origin):
        position = self.file.seek(offset, origin)
        if position < 0 or position > self.size:
            raise COMException(description="invalid stream seek", scode=winerror.STG_E_INVALIDFUNCTION)
        return position

    def SetSize(self, size):
        raise COMException(description="stream is read-only", scode=winerror.STG_E_ACCESSDENIED)

    def CopyTo(self, stream, count):
        data = self.Read(count)
        stream.Write(data)
        return len(data), len(data)

    def Commit(self, flags):
        return None

    def Revert(self):
        raise COMException(description="revert is unsupported", scode=winerror.STG_E_REVERTED)

    def LockRegion(self, offset, count, lock_type):
        raise COMException(description="locking is unsupported", scode=winerror.STG_E_INVALIDFUNCTION)

    def UnlockRegion(self, offset, count, lock_type):
        raise COMException(description="locking is unsupported", scode=winerror.STG_E_INVALIDFUNCTION)

    def Stat(self, flags):
        return (None, pythoncom.STGTY_STREAM, self.size, 0, 0, 0, 0, 0, 0, None)

    def Clone(self):
        return open_file_stream(self.path, self.size, self.file.tell())


def open_file_stream(path, size, position=0):
    return util.wrap(FileBackedStream(path, size, position), pythoncom.IID_IStream)


class CallbackStream:
    _com_interfaces_ = [pythoncom.IID_IStream]
    _public_methods_ = FileBackedStream._public_methods_

    def __init__(
        self, read_range, size, position=0, on_read=None,
        on_open=None, on_close=None,
    ):
        self.read_range = read_range
        self.size = size
        self.position = position
        self.on_read = on_read
        self.on_open = on_open
        self.on_close = on_close
        self.closed = False
        self.lock = threading.Lock()
        if on_open is not None:
            on_open()

    def __del__(self):
        self.close()

    def close(self):
        callback = None
        with self.lock:
            if not self.closed:
                self.closed = True
                callback = self.on_close
        if callback is not None:
            callback()

    def Read(self, count):
        with self.lock:
            offset = self.position
            try:
                data = self.read_range(offset, min(count, self.size - offset))
            except OSError as error:
                if getattr(error, "winerror", None) == 1223:
                    raise COMException(
                        description="the file operation was cancelled",
                        scode=-2147023673,
                    ) from None
                raise
            self.position += len(data)
            if data and self.on_read is not None:
                self.on_read(offset, len(data))
            return data

    def Write(self, data):
        raise COMException(description="stream is read-only", scode=winerror.STG_E_ACCESSDENIED)

    def Seek(self, offset, origin):
        with self.lock:
            if origin == 0:
                position = offset
            elif origin == 1:
                position = self.position + offset
            elif origin == 2:
                position = self.size + offset
            else:
                raise COMException(description="invalid stream seek", scode=winerror.STG_E_INVALIDFUNCTION)
            if position < 0 or position > self.size:
                raise COMException(description="invalid stream seek", scode=winerror.STG_E_INVALIDFUNCTION)
            self.position = position
            return position

    def SetSize(self, size):
        raise COMException(description="stream is read-only", scode=winerror.STG_E_ACCESSDENIED)

    def CopyTo(self, stream, count):
        data = self.Read(count)
        stream.Write(data)
        return len(data), len(data)

    def Commit(self, flags):
        return None

    def Revert(self):
        raise COMException(description="revert is unsupported", scode=winerror.STG_E_REVERTED)

    def LockRegion(self, offset, count, lock_type):
        raise COMException(description="locking is unsupported", scode=winerror.STG_E_INVALIDFUNCTION)

    def UnlockRegion(self, offset, count, lock_type):
        raise COMException(description="locking is unsupported", scode=winerror.STG_E_INVALIDFUNCTION)

    def Stat(self, flags):
        return (None, pythoncom.STGTY_STREAM, self.size, 0, 0, 0, 0, 0, 0, None)

    def Clone(self):
        return open_callback_stream(
            self.read_range, self.size, self.position, self.on_read,
            on_open=self.on_open, on_close=self.on_close,
        )


def open_callback_stream(
    read_range, size, position=0, on_read=None, on_open=None, on_close=None,
):
    return util.wrap(
        CallbackStream(
            read_range, size, position, on_read,
            on_open=on_open, on_close=on_close,
        ),
        pythoncom.IID_IStream,
    )


def build_file_group_descriptor(files: Iterable[VirtualFile]):
    items = tuple(files)
    if not items:
        raise ValueError("at least one virtual file is required")
    return struct.pack("<I", len(items)) + b"".join(
        _pack_file_descriptor(item) for item in items
    )


def parse_file_group_descriptor(data):
    if len(data) < 4:
        raise ValueError("file group descriptor is truncated")
    count = struct.unpack_from("<I", data)[0]
    expected_size = 4 + count * FILEDESCRIPTORW_SIZE
    if len(data) < expected_size or any(data[expected_size:]):
        raise ValueError("file group descriptor has an invalid size")
    data = data[:expected_size]

    parsed = []
    for index in range(count):
        offset = 4 + index * FILEDESCRIPTORW_SIZE
        attributes = struct.unpack_from("<I", data, offset + 36)[0]
        size_high, size_low = struct.unpack_from("<II", data, offset + 64)
        name_bytes = data[offset + 72:offset + FILEDESCRIPTORW_SIZE]
        terminator = _find_utf16_terminator(name_bytes)
        name = name_bytes[:terminator].decode("utf-16le")
        parsed.append(
            ParsedFileDescriptor(
                name=name,
                size=(size_high << 32) | size_low,
                is_directory=bool(attributes & FILE_ATTRIBUTE_DIRECTORY),
            )
        )
    return tuple(parsed)


def _pack_file_descriptor(item):
    flags = FD_ATTRIBUTES | FD_FILESIZE | FD_PROGRESSUI | FD_UNICODE
    if item.modified_filetime:
        flags |= FD_WRITESTIME
    attributes = FILE_ATTRIBUTE_DIRECTORY if item.is_directory else FILE_ATTRIBUTE_NORMAL
    size_high = (item.size >> 32) & 0xFFFFFFFF
    size_low = item.size & 0xFFFFFFFF
    modified_low = item.modified_filetime & 0xFFFFFFFF
    modified_high = (item.modified_filetime >> 32) & 0xFFFFFFFF
    name = item.name.encode("utf-16le") + b"\x00\x00"
    name = name.ljust(520, b"\x00")

    descriptor = struct.pack(
        "<I16s4iI6I2I",
        flags,
        b"\x00" * 16,
        0,
        0,
        0,
        0,
        attributes,
        0,
        0,
        0,
        0,
        modified_low,
        modified_high,
        size_high,
        size_low,
    ) + name
    if len(descriptor) != FILEDESCRIPTORW_SIZE:
        raise AssertionError("unexpected FILEDESCRIPTORW binary size")
    return descriptor


def _find_utf16_terminator(data):
    for index in range(0, len(data), 2):
        if data[index:index + 2] == b"\x00\x00":
            return index
    raise ValueError("virtual file name is not null terminated")
