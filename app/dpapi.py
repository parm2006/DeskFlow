"""Small Windows DPAPI wrapper used for local secrets and staging data."""
import ctypes
import os
from ctypes import wintypes

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

def protect(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    blob = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_ubyte)))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)

def unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        return data
    blob = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_ubyte)))
    out = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
