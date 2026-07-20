import threading
import time
import logging
import base64
import binascii
import zlib
import win32clipboard
import hashlib

from app.clipboard_offer import ClipboardKind, ClipboardOffer
from app.safe_errors import error_name

logger = logging.getLogger(__name__)

MAX_RICH_CLIPBOARD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_CLIPBOARD_BYTES = 50 * 1024 * 1024


class ClipboardPayloadError(ValueError):
    pass


def decode_compressed_clipboard_value(value, max_plaintext_bytes):
    if not isinstance(value, str):
        raise ClipboardPayloadError("compressed clipboard value must be text")
    if not isinstance(max_plaintext_bytes, int) or max_plaintext_bytes < 0:
        raise ValueError("clipboard plaintext limit must be non-negative")
    try:
        compressed = base64.b64decode(value, validate=True)
        decoder = zlib.decompressobj()
        plaintext = decoder.decompress(compressed, max_plaintext_bytes + 1)
    except (binascii.Error, ValueError, zlib.error) as error:
        raise ClipboardPayloadError("compressed clipboard value is invalid") from error
    if (
        len(plaintext) > max_plaintext_bytes
        or not decoder.eof
        or decoder.unconsumed_tail
        or decoder.unused_data
    ):
        raise ClipboardPayloadError(
            "compressed clipboard value exceeds its plaintext limit"
        )
    return plaintext


def encode_clipboard_snapshot(snapshot):
    """Encode a raw clipboard snapshot using DeskFlow's existing wire schema."""
    payload = {}
    text = snapshot.get('text')
    if text:
        payload['text'] = text

    for key in ('image', 'html', 'rtf'):
        data = snapshot.get(key)
        if data:
            compressed = zlib.compress(data, level=6)
            payload[key] = base64.b64encode(compressed).decode('utf-8')
    if not payload:
        payload['empty'] = True
    return payload

class ClipboardHandler:
    def __init__(
        self,
        on_clipboard_change,
        on_file_availability=None,
        on_clipboard_offer=None,
    ):
        self.on_clipboard_change = on_clipboard_change
        self.on_file_availability = on_file_availability
        self.on_clipboard_offer = on_clipboard_offer
        self.file_availability = None
        self._file_drop_format = win32clipboard.CF_HDROP
        self.last_sequence_num = None
        self.current_offer = ClipboardOffer(ClipboardKind.UNKNOWN, 0)
        self._offer_revision = 0
        self._state_lock = threading.RLock()
        self._run_generation = 0
        self.is_running = False
        self.thread = None
        self.is_injecting = False
        self.last_text_hash = None
        self.last_image_hash = None
        try:
            self.cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
            self.cf_rtf = win32clipboard.RegisterClipboardFormat("Rich Text Format")
        except Exception as error:
            logger.error(
                "Failed to register custom formats (%s)", error_name(error)
            )
            self.cf_html = None
            self.cf_rtf = None

    def start(self):
        if self.is_running:
            return
        with self._state_lock:
            self._run_generation += 1
            generation = self._run_generation
            self.is_running = True
        self.refresh_current_offer(force=True)
        self.thread = threading.Thread(
            target=self._poll_clipboard, args=(generation,), daemon=True
        )
        self.thread.start()
        logger.info("Rich Clipboard polling started (Native Zlib Compression)")

    def stop(self):
        with self._state_lock:
            self.is_running = False
            self._run_generation += 1
            thread = self.thread
        if thread is not None and threading.current_thread() is not thread:
            thread.join(timeout=1.5)
        if self.thread is thread:
            self.thread = None
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
        empty_clipboard = payload.get('empty') is True
        
        # Validations
        if text and not isinstance(text, str):
            logger.warning("Text payload is not a string")
            text = None
        elif text and len(text.encode("utf-8")) > MAX_RICH_CLIPBOARD_BYTES:
            logger.warning("Text payload exceeding 5MB limit")
            text = None
            
        if img_b64 and not isinstance(img_b64, str):
            logger.warning("Image payload is not a string")
            img_b64 = None
        elif img_b64 and len(img_b64) > MAX_IMAGE_CLIPBOARD_BYTES:
            logger.warning("Image payload exceeding 50MB limit")
            img_b64 = None

        if html_b64 and not isinstance(html_b64, str):
            logger.warning("HTML payload is not a string")
            html_b64 = None
        elif html_b64 and len(html_b64) > MAX_RICH_CLIPBOARD_BYTES:
            logger.warning("HTML payload exceeding 5MB limit")
            html_b64 = None

        if rtf_b64 and not isinstance(rtf_b64, str):
            logger.warning("RTF payload is not a string")
            rtf_b64 = None
        elif rtf_b64 and len(rtf_b64) > MAX_RICH_CLIPBOARD_BYTES:
            logger.warning("RTF payload exceeding 5MB limit")
            rtf_b64 = None

        if (
            not text and not img_b64 and not html_b64 and not rtf_b64
            and not empty_clipboard
        ):
            self.is_injecting = False
            return

        # Decompress/decode outside the clipboard lock!
        dib_data = None
        if img_b64:
            try:
                dib_data = decode_compressed_clipboard_value(
                    img_b64, MAX_IMAGE_CLIPBOARD_BYTES
                )
            except Exception as error:
                logger.error("Error decompressing image (%s)", error_name(error))
                self.is_injecting = False
                return

        html_data = None
        if html_b64 and self.cf_html:
            try:
                html_data = decode_compressed_clipboard_value(
                    html_b64, MAX_RICH_CLIPBOARD_BYTES
                )
            except Exception as error:
                logger.error("Error decompressing HTML (%s)", error_name(error))

        rtf_data = None
        if rtf_b64 and self.cf_rtf:
            try:
                rtf_data = decode_compressed_clipboard_value(
                    rtf_b64, MAX_RICH_CLIPBOARD_BYTES
                )
            except Exception as error:
                logger.error("Error decompressing RTF (%s)", error_name(error))

        # Record hashes of plain text and image to prevent forwarding back
        self.last_text_hash = self._get_hash(text)
        self.last_image_hash = self._get_hash(dib_data)

        injected_sequence = None
        clipboard_updated = False
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

                        # EmptyClipboard/SetClipboardData increments the sequence
                        # while DeskFlow still owns the open clipboard. Capture it
                        # before another process can write after CloseClipboard.
                        try:
                            injected_sequence = (
                                win32clipboard.GetClipboardSequenceNumber()
                            )
                        except Exception:
                            injected_sequence = None
                        logger.info("Injected rich clipboard payload (with formatting)")
                        clipboard_updated = True
                        break
                    finally:
                        win32clipboard.CloseClipboard()
                except Exception as error:
                    logger.debug(
                        "Clipboard locked during inject, retrying (%s)",
                        error_name(error),
                    )
                    time.sleep(0.1)
        finally:
            # Record only DeskFlow's write. A user copy made while Windows settles
            # must remain visible to the polling thread as a newer sequence.
            time.sleep(0.1)
            if injected_sequence is not None:
                self.last_sequence_num = injected_sequence
            try:
                self._update_file_availability()
            finally:
                self.is_injecting = False

    def _read_clipboard(self):
        snapshot = {}
        text_data = None
        dib_data = None
        html_data = None
        rtf_data = None
        
        read_succeeded = False
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
                        
                    read_succeeded = True
                    break
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as error:
                logger.debug(
                    "Clipboard locked during read, retrying (%s)",
                    error_name(error),
                )
                time.sleep(0.1)
                
        if not read_succeeded:
            return None

        if text_data:
            snapshot['text'] = text_data
        if dib_data:
            snapshot['image'] = dib_data

        if html_data:
            snapshot['html'] = html_data

        if rtf_data:
            snapshot['rtf'] = rtf_data
                
        return snapshot

    def _classify_clipboard(self):
        try:
            if win32clipboard.IsClipboardFormatAvailable(self._file_drop_format):
                return ClipboardKind.FILES, None
        except Exception as error:
            logger.debug(
                "Clipboard format classification failed (%s)", error_name(error)
            )
            return None

        snapshot = self._read_clipboard()
        if snapshot is None:
            return None
        return ClipboardKind.ORDINARY, snapshot

    def refresh_current_offer(self, force=False):
        """Classify one Windows clipboard sequence and publish one revision."""
        try:
            sequence = win32clipboard.GetClipboardSequenceNumber()
        except Exception as error:
            logger.debug("Clipboard sequence read failed (%s)", error_name(error))
            return None

        with self._state_lock:
            if not force and sequence == self.last_sequence_num:
                return self.current_offer

            classified = self._classify_clipboard()
            if classified is None:
                logger.info("Clipboard offer classification pending retry")
                return None

            kind, snapshot = classified
            self._offer_revision += 1
            offer = ClipboardOffer(kind, self._offer_revision)
            self.current_offer = offer
            self.last_sequence_num = sequence
            self._set_legacy_file_availability(kind is ClipboardKind.FILES)

        logger.info(
            "Local clipboard offer classified: kind=%s revision=%d",
            offer.kind.value,
            offer.revision,
        )
        delivered = True
        if self.on_clipboard_offer:
            try:
                if self.on_clipboard_offer(offer) is False:
                    delivered = False
            except Exception as error:
                delivered = False
                logger.error(
                    "Clipboard offer announcement failed (%s)", error_name(error)
                )
        if kind is ClipboardKind.ORDINARY:
            outgoing = dict(snapshot)
            outgoing["_deskflow_offer_revision"] = offer.revision
            try:
                if self.on_clipboard_change(outgoing) is False:
                    delivered = False
            except Exception as error:
                delivered = False
                logger.error(
                    "Clipboard payload scheduling failed (%s)", error_name(error)
                )
        if not delivered:
            with self._state_lock:
                if self.current_offer == offer and self.last_sequence_num == sequence:
                    self.last_sequence_num = None
        return offer

    def _set_legacy_file_availability(self, available):
        if available == self.file_availability:
            return
        self.file_availability = available
        logger.info(
            "Local clipboard file offer changed: available=%s",
            str(available).lower(),
        )
        if self.on_file_availability:
            self.on_file_availability(available)

    def _update_file_availability(self):
        try:
            available = bool(
                win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP)
            )
        except Exception:
            available = False
        self._set_legacy_file_availability(available)

    def read_file_selection(self):
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(self._file_drop_format):
                return ()
            paths = win32clipboard.GetClipboardData(self._file_drop_format)
            return tuple(paths)
        finally:
            win32clipboard.CloseClipboard()

    def _poll_clipboard(self, generation):
        while self.is_running and generation == self._run_generation:
            try:
                if self.is_injecting:
                    time.sleep(0.1)
                    continue
                self.refresh_current_offer()
            except Exception as error:
                logger.error("Error in poll clipboard (%s)", error_name(error))
            time.sleep(0.5)
