from dataclasses import dataclass
from enum import Enum


class ClipboardKind(str, Enum):
    ORDINARY = "ordinary"
    FILES = "files"


class ClipboardOrigin(str, Enum):
    UNKNOWN = "unknown"
    LOCAL = "local"
    REMOTE = "remote"


@dataclass
class ClipboardAuthority:
    local_active: bool = False
    origin: ClipboardOrigin = ClipboardOrigin.UNKNOWN
    kind: ClipboardKind | None = None

    def set_local_active(self, active):
        self.local_active = active is True

    def note_local_copy(self, kind):
        if not self.local_active:
            return False
        self.origin = ClipboardOrigin.LOCAL
        self.kind = ClipboardKind(kind)
        return True

    def may_accept_remote(self):
        return not (
            self.local_active and self.origin is ClipboardOrigin.LOCAL
        )

    def may_accept_remote_ordinary(self):
        return (
            self.may_accept_remote()
            and not (
                self.origin is ClipboardOrigin.REMOTE
                and self.kind is ClipboardKind.FILES
            )
        )

    def note_remote_copy(self, kind):
        if not self.may_accept_remote():
            return False
        self.origin = ClipboardOrigin.REMOTE
        self.kind = ClipboardKind(kind)
        return True

    def reset(self):
        self.origin = ClipboardOrigin.UNKNOWN
        self.kind = None
