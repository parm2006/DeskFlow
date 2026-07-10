import pyperclip
import threading
import time
import logging

logger = logging.getLogger(__name__)

class ClipboardHandler:
    def __init__(self, on_clipboard_change):
        self.on_clipboard_change = on_clipboard_change
        self.last_seen_content = ""
        self.last_injected_content = ""
        self.is_running = False
        self.thread = None

    def start(self):
        self.is_running = True
        try:
            self.last_seen_content = pyperclip.paste()
        except Exception:
            self.last_seen_content = ""
            
        self.thread = threading.Thread(target=self._poll_clipboard, daemon=True)
        self.thread.start()
        logger.info("Clipboard polling started")

    def stop(self):
        self.is_running = False
        # Phase 3.5 Security: Wipe clipboard on stop
        try:
            pyperclip.copy("")
            logger.info("Clipboard securely wiped on disconnect")
        except Exception as e:
            logger.error(f"Failed to wipe clipboard: {e}")
        
    def inject(self, text):
        # Phase 3.5 Security: Validate payload
        if not isinstance(text, str):
            logger.warning("Received invalid clipboard payload type")
            return
            
        # 5MB limit to prevent memory exhaustion
        if len(text) > 1024 * 1024 * 5:
            logger.warning("Received clipboard payload exceeding 5MB limit")
            return
            
        try:
            self.last_injected_content = text
            self.last_seen_content = text # Prevent poller from bouncing it back
            pyperclip.copy(text)
            logger.info("Injected clipboard payload")
        except Exception as e:
            logger.error(f"Failed to inject clipboard: {e}")

    def _poll_clipboard(self):
        while self.is_running:
            try:
                current = pyperclip.paste()
                if current != self.last_seen_content:
                    self.last_seen_content = current
                    if current != self.last_injected_content:
                        logger.info("Local clipboard change detected, forwarding...")
                        self.on_clipboard_change(current)
            except Exception:
                pass
            time.sleep(0.5)
