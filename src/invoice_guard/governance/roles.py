"""Local simulation of identity governance (config/users.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROLE_PROCUREMENT = "procurement"  # may submit invoices
ROLE_CFO = "cfo"                  # the only role that may record a payment decision
ROLE_ANALYST = "analyst"          # may promote drafted contract rules


class Directory:
    def __init__(self, users_file: Path):
        data = yaml.safe_load(users_file.read_text("utf-8")) or {}
        self._users = {k.lower(): v for k, v in (data.get("users") or {}).items()}

    def roles(self, email: str) -> set[str]:
        return set((self._users.get((email or "").lower()) or {}).get("roles", []))

    def has_role(self, email: str, role: str) -> bool:
        return role in self.roles(email)
