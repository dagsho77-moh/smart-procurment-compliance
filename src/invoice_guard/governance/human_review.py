"""HUMAN review gate - the ONLY place a payment decision can be recorded.

* Not importable from agents/tools/checks/knowledge/llm/workflow/storage
  (enforced by import-linter in pyproject.toml and by tests/test_agent_boundaries.py).
* Requires a reviewer with the CFO role.
* Refuses documents that are not invoices; requires an explicit acknowledgement to
  approve anything on security hold.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from invoice_guard.config import Settings
from invoice_guard.governance.roles import ROLE_CFO, Directory
from invoice_guard.storage.registry import InvoiceRegistry


class HumanDecision(str, Enum):
    APPROVED_BY_HUMAN = "APPROVED_BY_HUMAN"
    REJECTED_BY_HUMAN = "REJECTED_BY_HUMAN"


class ReviewError(PermissionError):
    pass


@dataclass(frozen=True)
class DecisionRecord:
    invoice_number: str
    decision: HumanDecision
    reviewer: str
    decided_at: str


def record_decision(
    settings: Settings,
    *,
    invoice_number: str,
    reviewer: str,
    decision: HumanDecision,
    note: str = "",
    acknowledge_security_hold: bool = False,
) -> DecisionRecord:
    directory = Directory(settings.paths.users_file)
    if not directory.has_role(reviewer, ROLE_CFO):
        raise ReviewError(f"{reviewer} does not hold the '{ROLE_CFO}' role; decision refused.")

    registry = InvoiceRegistry(settings.paths.registry_db)
    try:
        records = registry.find_by_invoice_number(invoice_number)
    finally:
        registry.close()
    if not records:
        raise ReviewError(f"No audited invoice with number {invoice_number}.")
    record = records[-1]
    if record.status == "RETURNED_NOT_AN_INVOICE":
        raise ReviewError("Document was classified as not an invoice; nothing to decide.")
    if (record.status == "BLOCKED_SECURITY_HOLD" and decision is HumanDecision.APPROVED_BY_HUMAN
            and not acknowledge_security_hold):
        raise ReviewError("Invoice is on SECURITY HOLD. Verify the vendor out-of-band, then re-run "
                          "with --acknowledge-security-hold.")

    decided_at = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(settings.paths.registry_db) as conn:
        conn.execute(
            "INSERT INTO human_decisions (invoice_record_id, invoice_number, decision, reviewer, note, decided_at) "
            "VALUES (?,?,?,?,?,?)",
            (record.id, invoice_number, decision.value, reviewer.lower(), note, decided_at),
        )
    log = settings.paths.traces_dir / "human_decisions.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": decided_at, "invoice_number": invoice_number,
                             "automated_status": record.status, "decision": decision.value,
                             "reviewer": reviewer.lower(), "note": note,
                             "acknowledged_security_hold": acknowledge_security_hold}) + "\n")
    return DecisionRecord(invoice_number, decision, reviewer.lower(), decided_at)
