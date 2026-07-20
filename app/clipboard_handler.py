import threading
import time
import logging
import base64
import binascii
import zlib
import win32clipboard

from app.clipboard_authority import ClipboardKind
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
        on_clipboard_kind=None,
        state_lock=None,
        poll_interval=0.1,
    ):
        self.on_clipboard_change = on_clipboard_change
        self.on_file_availability = on_file_availability
        self.on_clipboard_kind = on_clipboard_kind
        self._state_lock = state_lock or threading.RLock()
        self.poll_interval = float(poll_interval)
        self.active = True
        self.file_availability = None
        self._file_drop_format = win32clipboard.CF_HDROP
        self.last_sequence_num = 0
        self.is_running = False
        self.thread = None
        self.is_injecting = False
        try:
            self.cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
            self.cf_rtf = win32clipboard.RegisterClipboardFormat("Rich Text Format")
        except Exception as error:
            logger.error(
                "Failed to register custom formats (%s)", error_name(error)
            )
            self.cf_html = None
            self.cf_rtf = None

    def set_active(self, active):
        with self._state_lock:
            self.active = active is True

    def start(self):
        self.is_running = True
        try:
            self.last_sequence_num = win32clipboard.GetClipboardSequenceNumber()
        except:
            pass
        self._update_file_availability(notify=False)
        if self.active and self.file_availability and self.on_clipboard_kind:
            self.on_clipboard_kind(ClipboardKind.FILES)
        self.thread = threading.Thread(target=self._poll_clipboard, daemon=True)
        self.thread.start()
        logger.info("Rich Clipboard polling started (Native Zlib Compression)")

    def stop(self):
        self.is_running = False
        self.wipe_clipboard()

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
        with self._state_lock:
            return self._inject_locked(payload)

    def _inject_locked(self, payload):
        self.is_injecting = True
        try:
            text = payload.get('text')
            img_b64 = payload.get('image')
            html_b64 = payload.get('html')
            rtf_b64 = payload.get('rtf')
            empty_clipboard = payload.get('empty') is True

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
                return False

            dib_data = None
            if img_b64:
                dib_data = decode_compressed_clipboard_value(
                    img_b64, MAX_IMAGE_CLIPBOARD_BYTES
                )

            html_data = None
            if html_b64 and self.cf_html:
                html_data = decode_compressed_clipboard_value(
                    html_b64, MAX_RICH_CLIPBOARD_BYTES
                )

            rtf_data = None
            if rtf_b64 and self.cf_rtf:
                rtf_data = decode_compressed_clipboard_value(
                    rtf_b64, MAX_RICH_CLIPBOARD_BYTES
                )

            expected_sequence = self.last_sequence_num
            injected_sequence = None
            for _ in range(5):
                try:
                    win32clipboard.OpenClipboard()
                    try:
                        try:
                            current_sequence = (
                                win32clipboard.GetClipboardSequenceNumber()
                            )
                        except Exception as error:
                            logger.info(
                                "Remote clipboard injection rejected: sequence unreadable (%s)",
                                error_name(error),
                            )
                            return False
                        if (
                            self.active
                            and expected_sequence is not None
                            and current_sequence != expected_sequence
                        ):
                            logger.info(
                                "Remote clipboard injection rejected: newer local sequence"
                            )
                            return False

                        win32clipboard.EmptyClipboard()

                        if text:
                            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)

                        if dib_data:
                            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)

                        if html_data:
                            win32clipboard.SetClipboardData(self.cf_html, html_data)

                        if rtf_data:
                            win32clipboard.SetClipboardData(self.cf_rtf, rtf_data)

                        injected_sequence = (
                            win32clipboard.GetClipboardSequenceNumber()
                        )
                        self.last_sequence_num = injected_sequence
                        logger.info("Injected rich clipboard payload (with formatting)")
                        return True
                    finally:
                        win32clipboard.CloseClipboard()
                except Exception as error:
                    logger.debug(
                        "Clipboard locked during inject, retrying (%s)",
                        error_name(error),
                    )
                    time.sleep(0.1)
            return False
        except Exception as error:
            logger.error("Remote clipboard payload rejected (%s)", error_name(error))
            return False
        finally:
            try:
                self._update_file_availability(notify=False)
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

    def _update_file_availability(self, notify=True):
        try:
            available = bool(
                win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_HDROP)
            )
        except Exception:
            available = False
        self._set_file_availability(available, notify=notify)

    def _set_file_availability(self, available, notify=True):
        available = available is True
        if available == self.file_availability:
            return
        self.file_availability = available
        if notify and self.on_file_availability:
            self.on_file_availability(available)

    def process_current_sequence(self):
        with self._state_lock:
            return self._process_current_sequence_locked()

    def _process_current_sequence_locked(self):
        try:
            sequence = win32clipboard.GetClipboardSequenceNumber()
        except Exception:
            return False
        if sequence == self.last_sequence_num:
            return False

        try:
            files_available = bool(
                win32clipboard.IsClipboardFormatAvailable(self._file_drop_format)
            )
        except Exception:
            return False

        if files_available:
            kind = ClipboardKind.FILES
            snapshot = None
        else:
            kind = ClipboardKind.ORDINARY
            snapshot = self._read_clipboard()
            if snapshot is None:
                return False

        self.last_sequence_num = sequence
        self._set_file_availability(files_available, notify=False)
        logger.info(
            "Clipboard sequence classified: sequence=%s active=%s kind=%s",
            sequence,
            self.active,
            kind.value,
        )
        if not self.active:
            return True
        if self.on_clipboard_kind:
            self.on_clipboard_kind(kind)
        if kind is ClipboardKind.ORDINARY:
            self.on_clipboard_change(snapshot)
        return True

    def read_file_selection(self):
        win32clipboard.OpenClipboard()
        try:
            if not win32clipboard.IsClipboardFormatAvailable(self._file_drop_format):
                return ()
            paths = win32clipboard.GetClipboardData(self._file_drop_format)
            return tuple(paths)
        finally:
            win32clipboard.CloseClipboard()

    def _poll_clipboard(self):
        while self.is_running:
            try:
                if self.is_injecting:
                    time.sleep(0.1)
                    continue
                self.process_current_sequence()
            except Exception as error:
                logger.error("Error in poll clipboard (%s)", error_name(error))
            time.sleep(self.poll_interval)
