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
        try:
            self.cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
            self.cf_rtf = win32clipboard.RegisterClipboardFormat("Rich Text Format")
        except Exception as e:
            logger.error(f"Failed to register custom formats: {e}")
            self.cf_html = None
            self.cf_rtf = None

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
        html_b64 = payload.get('html')
        rtf_b64 = payload.get('rtf')
        
        # Validations
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

        if html_b64 and not isinstance(html_b64, str):
            logger.warning("HTML payload is not a string")
            html_b64 = None
        elif html_b64 and len(html_b64) > 1024 * 1024 * 5:
            logger.warning("HTML payload exceeding 5MB limit")
            html_b64 = None

        if rtf_b64 and not isinstance(rtf_b64, str):
            logger.warning("RTF payload is not a string")
            rtf_b64 = None
        elif rtf_b64 and len(rtf_b64) > 1024 * 1024 * 5:
            logger.warning("RTF payload exceeding 5MB limit")
            rtf_b64 = None

        if not text and not img_b64 and not html_b64 and not rtf_b64:
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

        html_data = None
        if html_b64 and self.cf_html:
            try:
                html_data = zlib.decompress(base64.b64decode(html_b64))
            except Exception as e:
                logger.error(f"Error decompressing HTML: {e}")

        rtf_data = None
        if rtf_b64 and self.cf_rtf:
            try:
                rtf_data = zlib.decompress(base64.b64decode(rtf_b64))
            except Exception as e:
                logger.error(f"Error decompressing RTF: {e}")

        # Record hashes of plain text and image to prevent forwarding back
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

                        if html_data:
                            win32clipboard.SetClipboardData(self.cf_html, html_data)

                        if rtf_data:
                            win32clipboard.SetClipboardData(self.cf_rtf, rtf_data)
                            
                        logger.info("Injected rich clipboard payload (with formatting)")
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
        html_data = None
        rtf_data = None
        
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                        text_data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                        
                    if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                        dib_data = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)

                    if self.cf_html and win32clipboard.IsClipboardFormatAvailable(self.cf_html):
                        html_data = win32clipboard.GetClipboardData(self.cf_html)

                    if self.cf_rtf and win32clipboard.IsClipboardFormatAvailable(self.cf_rtf):
                        rtf_data = win32clipboard.GetClipboardData(self.cf_rtf)
                        
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

        if html_data:
            try:
                # html_data is raw bytes (utf-8 with windows header)
                compressed = zlib.compress(html_data, level=6)
                payload['html'] = base64.b64encode(compressed).decode('utf-8')
            except Exception as e:
                logger.error(f"Failed to compress HTML payload: {e}")

        if rtf_data:
            try:
                # rtf_data is raw bytes (ansi RTF string bytes)
                compressed = zlib.compress(rtf_data, level=6)
                payload['rtf'] = base64.b64encode(compressed).decode('utf-8')
            except Exception as e:
                logger.error(f"Failed to compress RTF payload: {e}")
                
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
