"""Non-secret local DeskFlow UI preferences."""

import json
import logging
import os
from pathlib import Path
import uuid

from app.safe_errors import error_name


logger = logging.getLogger(__name__)
VALID_ROLES = frozenset(("server", "client"))
VALID_CLIENT_POSITIONS = frozenset(("top", "left", "right", "bottom"))


class UserPreferences:
    def __init__(self, root=None):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DeskFlow"
        self.root = Path(root or base).resolve()
        self.path = self.root / "preferences.json"

    def load_role(self):
        role = self._load_values().get("last_successful_role")
        return role if role in VALID_ROLES else None

    def load_client_position(self):
        position = self._load_values().get("client_position")
        return position if position in VALID_CLIENT_POSITIONS else "right"

    def save_role(self, role):
        if role not in VALID_ROLES:
            raise ValueError("role must be server or client")
        self._save_value("last_successful_role", role)

    def save_client_position(self, position):
        if position not in VALID_CLIENT_POSITIONS:
            raise ValueError("client position must be top, left, right, or bottom")
        self._save_value("client_position", position)

    def _load_values(self):
        if not self.path.exists():
            return {}
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
            return values if isinstance(values, dict) else {}
        except Exception as error:
            logger.error("Could not load DeskFlow preferences (%s)", error_name(error))
            return {}

    def _save_value(self, key, value):
        self.root.mkdir(parents=True, exist_ok=True)
        values = self._load_values()
        values[key] = value
        payload = json.dumps(values, separators=(",", ":"))
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
