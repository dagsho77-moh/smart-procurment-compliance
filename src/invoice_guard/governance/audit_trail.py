"""Traces: an append-only JSONL audit trail for every step of every invoice."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


def _default(obj: Any) -> Any:
    if isinstance(obj, (Decimal, Path)):
        return str(obj)
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "value"):
        return obj.value
    raise TypeError(f"not serialisable: {type(obj)}")


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


class AuditTrail:
    def __init__(self, traces_dir: Path, run_id: str | None = None):
        self.run_id = run_id or new_run_id()
        traces_dir.mkdir(parents=True, exist_ok=True)
        self.path = traces_dir / f"{self.run_id}.jsonl"

    def event(self, document: str, step: str, **data: Any) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "document": document,
            "step": step,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=_default, ensure_ascii=False) + "\n")
