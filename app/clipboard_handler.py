import threading
import time
import logging
import base64
import zlib
import win32clipboard
import hashlib

logger = logging.getLogger(__name__)

class ClipboardHandler:
    def __init__(self, on_clipboard_change):
        self.on_clipboard_change = on_clipboard_change
        self.last_sequence_num = 0
        self.is_running = False
        self.thread = None
        self.is_injecting = False
        self.last_text_hash = None
        self.last_image_hash = None

    def start(self):
        self.is_running = True
        try:
            self.last_sequence_num = win32clipboard.GetClipboardSequenceNumber()
        except:
            pass
        self.thread = threading.Thread(target=self._poll_clipboard, daemon=True)
        self.thread.start()
        logger.info("Rich Clipboard polling started (Native Zlib Compression)")

    def stop(self):
        self.is_running = False
        self.wipe_clipboard()

    def _get_hash(self, data):
        if not data:
            return None
        if isinstance(data, str):
            data = data.encode('utf-8', errors='ignore')
        return hashlib.md5(data).hexdigest()

    def wipe_clipboard(self):
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    logger.info("Clipboard securely wiped on disconnect")
                    break
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as e:
                time.sleep(0.1)
        
    def inject(self, payload):
        self.is_injecting = True
        
        text = payload.get('text')
        img_b64 = payload.get('image')
        
        if text and not isinstance(text, str):
            logger.warning("Text payload is not a string")
            text = None
        elif text and len(text) > 1024 * 1024 * 5:
            logger.warning("Text payload exceeding 5MB limit")
            text = None
            
        if img_b64 and not isinstance(img_b64, str):
            logger.warning("Image payload is not a string")
            img_b64 = None
        elif img_b64 and len(img_b64) > 1024 * 1024 * 50:
            logger.warning("Image payload exceeding 50MB limit")
            img_b64 = None

        if not text and not img_b64:
            self.is_injecting = False
            return

        # Decompress/decode outside the clipboard lock!
        dib_data = None
        if img_b64:
            try:
                dib_data = zlib.decompress(base64.b64decode(img_b64))
            except Exception as e:
                logger.error(f"Error decompressing image: {e}")
                self.is_injecting = False
                return

        # Record hashes to prevent forwarding back
        self.last_text_hash = self._get_hash(text)
        self.last_image_hash = self._get_hash(img_b64)

        try:
            for _ in range(5):
                try:
                    win32clipboard.OpenClipboard()
                    try:
                        win32clipboard.EmptyClipboard()
                        
                        if text:
                            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
                            
                        if dib_data:
                            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
                            
                        logger.info("Injected rich clipboard payload")
                        break
                    finally:
                        win32clipboard.CloseClipboard()
                except Exception as e:
                    logger.debug(f"Clipboard locked during inject, retrying... {e}")
                    time.sleep(0.1)
        finally:
            # Let the OS settle, then fetch the updated sequence number
            time.sleep(0.1)
            try:
                self.last_sequence_num = win32clipboard.GetClipboardSequenceNumber()
            except:
                pass
            self.is_injecting = False

    def _read_clipboard(self):
        payload = {}
        text_data = None
        dib_data = None
        
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                        text_data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                        
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                        dib_data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
                        
                    break
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as e:
                logger.debug(f"Clipboard locked during read, retrying... {e}")
                time.sleep(0.1)
                
        if text_data:
            payload['text'] = text_data
        if dib_data:
            try:
                # Compress native DIB bytes outside of clipboard lock
                compressed = zlib.compress(dib_data, level=6)
                payload['image'] = base64.b64encode(compressed).decode('utf-8')
            except Exception as e:
                logger.error(f"Failed to compress DIB: {e}")
                
        return payload

    def _poll_clipboard(self):
        while self.is_running:
            try:
                if self.is_injecting:
                    time.sleep(0.1)
                    continue
                seq = win32clipboard.GetClipboardSequenceNumber()
                if seq != self.last_sequence_num:
                    self.last_sequence_num = seq
                    
                    payload = self._read_clipboard()
                    if payload:
                        text = payload.get('text')
                        image = payload.get('image')
                        
                        text_hash = self._get_hash(text)
                        image_hash = self._get_hash(image)
                        
                        # Only send if there is actual content AND it is different from last sent/injected
                        is_new_text = text and text_hash != self.last_text_hash
                        is_new_image = image and image_hash != self.last_image_hash
                        
                        if is_new_text or is_new_image:
                            logger.info("Local rich clipboard change detected, forwarding...")
                            # Update hashes
                            if is_new_text:
                                self.last_text_hash = text_hash
                            if is_new_image:
                                self.last_image_hash = image_hash
                                
                            self.on_clipboard_change(payload)
            except Exception as e:
                logger.error(f"Error in poll clipboard: {e}")
            time.sleep(0.5)
