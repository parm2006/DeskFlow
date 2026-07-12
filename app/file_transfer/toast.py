import customtkinter as ctk

from app.input_geometry import windows_work_area
from .status import TransferPhase


class TransferToast:
    def __init__(self, root, on_cancel):
        self.root = root
        self.on_cancel = on_cancel
        self.job_id = None
        self._hide_after = None
        self.window = ctk.CTkToplevel(root)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.geometry("360x150")
        self.title = ctk.CTkLabel(self.window, text="", font=ctk.CTkFont(size=15, weight="bold"), anchor="w")
        self.title.pack(fill="x", padx=16, pady=(14, 4))
        self.progress = ctk.CTkProgressBar(self.window)
        self.progress.pack(fill="x", padx=16, pady=4)
        self.details = ctk.CTkLabel(self.window, text="", anchor="w")
        self.details.pack(fill="x", padx=16, pady=2)
        self.cancel = ctk.CTkButton(self.window, text="Cancel", width=76, height=28, command=self._cancel)
        self.cancel.pack(anchor="e", padx=16, pady=(4, 12))

    def show(self, status):
        if self._hide_after is not None:
            self.root.after_cancel(self._hide_after)
            self._hide_after = None
        self.job_id = status.job_id
        self.title.configure(text=f"{status.phase.value.title()} · {status.label}")
        percent = status.percent
        self.progress.configure(mode="indeterminate" if percent is None else "determinate")
        if percent is None:
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.set(percent / 100.0)
        self.details.configure(text=_details(status))
        self.cancel.configure(state="disabled" if status.is_terminal else "normal")
        left, top, right, bottom = windows_work_area()
        self.window.geometry(f"360x150+{right - 376}+{bottom - 166}")
        self.window.deiconify()
        if status.phase is TransferPhase.COMPLETED:
            self._hide_after = self.root.after(3000, self.window.withdraw)
        elif status.phase is TransferPhase.CANCELLED:
            self._hide_after = self.root.after(5000, self.window.withdraw)

    def _cancel(self):
        if self.job_id:
            self.on_cancel(self.job_id)


def _details(status):
    done = _size(status.bytes_done)
    total = _size(status.bytes_total)
    if status.phase is TransferPhase.FAILED:
        return "Transfer failed. Check the DeskFlow log."
    if status.bytes_per_second > 0:
        speed = f"{_size(status.bytes_per_second)}/s"
        eta = "" if status.eta_seconds is None else f" · about {max(1, round(status.eta_seconds))}s left"
        return f"{done} / {total} · {speed}{eta}"
    return f"{done} / {total}"


def _size(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
