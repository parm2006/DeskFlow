"""Opt-in Explorer/Desktop smoke test for DeskFlow's virtual-file provider."""

import time

import pythoncom

from app.windows_virtual_files import VirtualFile, VirtualFileSet, publish_virtual_files


def main():
    pythoncom.OleInitialize()
    try:
        files = VirtualFileSet(
            [
                VirtualFile("DeskFlow virtual one.txt", 21, lambda: b"DeskFlow virtual one\n"),
                VirtualFile("DeskFlow virtual two.txt", 21, lambda: b"DeskFlow virtual two\n"),
            ]
        )
        owner = publish_virtual_files(files)
        print("Two virtual files are on the clipboard for 60 seconds.")
        print("Paste into an empty Explorer folder or onto the Desktop.")
        print("While a paste is active, copy ordinary text and confirm the paste still finishes.")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            pythoncom.PumpWaitingMessages()
            time.sleep(0.01)
        return owner
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
