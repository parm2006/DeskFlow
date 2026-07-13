from dataclasses import dataclass
from enum import Enum


class TransferPhase(str, Enum):
    PREPARING = "preparing"
    COMPRESSING = "compressing"
    TRANSFERRING = "transferring"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_FOR_EXPLORER = "waiting_for_explorer"
    PASTING = "pasting"
    VERIFYING_RESULT = "verifying_result"
    CANCELLING = "cancelling"


_TERMINAL_PHASES = {
    TransferPhase.COMPLETED,
    TransferPhase.FAILED,
    TransferPhase.CANCELLED,
}


@dataclass(frozen=True)
class TransferStatus:
    job_id: str
    phase: TransferPhase
    label: str
    bytes_done: int
    bytes_total: int
    bytes_per_second: float = 0.0
    error_code: str | None = None

    @property
    def percent(self):
        if self.phase in {TransferPhase.PREPARING, TransferPhase.WAITING_FOR_EXPLORER} or self.bytes_total <= 0:
            return None
        return min(100.0, self.bytes_done * 100.0 / self.bytes_total)

    @property
    def eta_seconds(self):
        if self.bytes_per_second <= 0 or self.bytes_total <= self.bytes_done:
            return None
        return (self.bytes_total - self.bytes_done) / self.bytes_per_second

    @property
    def is_terminal(self):
        return self.phase in _TERMINAL_PHASES

    def to_public_dict(self):
        return {
            "job_id": self.job_id,
            "phase": self.phase.value,
            "label": self.label,
            "bytes_done": self.bytes_done,
            "bytes_total": self.bytes_total,
            "bytes_per_second": self.bytes_per_second,
            "percent": self.percent,
            "eta_seconds": self.eta_seconds,
            "error_code": self.error_code,
        }
