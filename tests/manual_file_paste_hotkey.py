"""Manual Windows check for selective Ctrl+V suppression."""

import time

from app.file_transfer.hotkey import WindowsPasteHotkeyMonitor
from app.file_transfer.paste_coordinator import PasteCoordinator


def main():
    requests = []
    coordinator = PasteCoordinator(lambda: (requests.append(time.monotonic()), print("REMOTE FILE PASTE DETECTED")))
    monitor = WindowsPasteHotkeyMonitor(coordinator)
    monitor.start()
    try:
        print("For 10 seconds: paste ordinary copied text into Notepad. It MUST paste normally.")
        time.sleep(10)
        coordinator.set_remote_files_available(True)
        print("For 15 seconds: press Ctrl+V in Notepad. Nothing should paste, and this window must print detection once.")
        time.sleep(15)
        coordinator.set_remote_files_available(False)
        print("For 10 seconds: press Ctrl+V again. It MUST paste normally.")
        time.sleep(10)
        print(f"Detected remote file paste requests: {len(requests)}")
    finally:
        monitor.stop()


if __name__ == "__main__":
    main()
