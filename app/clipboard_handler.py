import threading
import time
import logging
import base64
import win32clipboard
from PIL import ImageGrab, Image
import io

logger = logging.getLogger(__name__)

class ClipboardHandler:
    def __init__(self, on_clipboard_change):
        self.on_clipboard_change = on_clipboard_change
        self.last_sequence_num = 0
        self.is_running = False
        self.thread = None
        self.ignore_next_sequence = False

    def start(self):
        self.is_running = True
        try:
            self.last_sequence_num = win32clipboard.GetClipboardSequenceNumber()
        except:
            pass
        self.thread = threading.Thread(target=self._poll_clipboard, daemon=True)
        self.thread.start()
        logger.info("Rich Clipboard polling started")

    def stop(self):
        self.is_running = False
        self.wipe_clipboard()

    def wipe_clipboard(self):
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
                logger.info("Clipboard securely wiped on disconnect")
                break
            except Exception as e:
                time.sleep(0.1)
        
    def inject(self, payload):
        self.ignore_next_sequence = True
        
        text = payload.get('text')
        img_b64 = payload.get('image')
        
        if text and len(text) > 1024 * 1024 * 5:
            logger.warning("Text payload exceeding 5MB limit")
            text = None
            
        if img_b64 and len(img_b64) > 1024 * 1024 * 20:
            logger.warning("Image payload exceeding 20MB limit")
            img_b64 = None

        if not text and not img_b64:
            return

        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                
                if text:
                    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
                    
                if img_b64:
                    png_bytes = base64.b64decode(img_b64)
                    img = Image.open(io.BytesIO(png_bytes))
                    
                    output = io.BytesIO()
                    img.convert("RGB").save(output, "BMP")
                    dib_data = output.getvalue()[14:]
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
                    
                win32clipboard.CloseClipboard()
                logger.info("Injected rich clipboard payload")
                
                # Update sequence number immediately to prevent bounce back
                self.last_sequence_num = win32clipboard.GetClipboardSequenceNumber()
                break
            except Exception as e:
                logger.debug(f"Clipboard locked during inject, retrying... {e}")
                time.sleep(0.1)

    def _read_clipboard(self):
        payload = {}
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                    payload['text'] = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                
                # Use Pillow to grab image (Pillow handles opening/closing clipboard internally for DIB)
                try:
                    img = ImageGrab.grabclipboard()
                    if isinstance(img, Image.Image):
                        with io.BytesIO() as output:
                            img.save(output, format="PNG", optimize=True)
                            payload['image'] = base64.b64encode(output.getvalue()).decode('utf-8')
                except Exception as e:
                    logger.error(f"Failed to read image from clipboard: {e}")
                    
                return payload
            except Exception as e:
                logger.debug(f"Clipboard locked during read, retrying... {e}")
                time.sleep(0.1)
                
        return None

    def _poll_clipboard(self):
        while self.is_running:
            try:
                seq = win32clipboard.GetClipboardSequenceNumber()
                if seq != self.last_sequence_num:
                    self.last_sequence_num = seq
                    
                    if self.ignore_next_sequence:
                        self.ignore_next_sequence = False
                        continue
                        
                    payload = self._read_clipboard()
                    if payload and (payload.get('text') or payload.get('image')):
                        logger.info("Local rich clipboard change detected, forwarding...")
                        self.on_clipboard_change(payload)
            except Exception:
                pass
            time.sleep(0.5)
