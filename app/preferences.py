"""Non-secret local DeskFlow UI preferences."""

import json
import logging
import os
from pathlib import Path
import uuid

from app.safe_errors import error_name


logger = logging.getLogger(__name__)
VALID_ROLES = frozenset(("server", "client"))


class UserPreferences:
    def __init__(self, root=None):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeskFlow"
        self.root = Path(root or base).resolve()
        self.path = self.root / "preferences.json"

    def load_role(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            role = value.get("last_successful_role")
            return role if role in VALID_ROLES else None
        except Exception as error:
            logger.error("Could not load DeskFlow preferences (%s)", error_name(error))
            return None

    def save_role(self, role):
        if role not in VALID_ROLES:
            raise ValueError("role must be server or client")
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"last_successful_role": role}, separators=(",", ":")
        )
        temporary = self.path.with_name(
            f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
