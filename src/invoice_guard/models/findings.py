"""Flags, statuses and the agent verdict.

Gora's rule #4 at the type level: there is deliberately NO "approved" member in
InvoiceStatus. An automated component cannot even represent an approval.
Human payment decisions live in invoice_guard.governance.human_review only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "INFO"          # recorded for the audit trail, no action needed
    WARNING = "WARNING"    # needs human attention
    CRITICAL = "CRITICAL"  # serious risk

    @property
    def rank(self) -> int:
        return {"INFO": 0, "WARNING": 1, "CRITICAL": 2}[self.value]


class Category(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    SECURITY = "security"
    MATH = "math"
    DUPLICATE = "duplicate"
    PO_MATCH = "po"
    CONTRACT = "contract"
    POLICY = "policy"
    ADVISORY = "advisory"
    PIPELINE = "pipeline"


class InvoiceStatus(str, Enum):
    """Every status an AUTOMATED component may assign. None of them is an approval."""

    RETURNED_NOT_AN_INVOICE = "RETURNED_NOT_AN_INVOICE"
    BLOCKED_SECURITY_HOLD = "BLOCKED_SECURITY_HOLD"
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"
    READY_FOR_CFO_REVIEW = "READY_FOR_CFO_REVIEW"  # "no issues found" is NOT an approval


@dataclass(frozen=True)
class Flag:
    check: str                 # e.g. "math.total_mismatch", "contract.shipping_free"
    category: Category
    severity: Severity
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    source: str = "deterministic"  # "deterministic" | "llm"

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "evidence": self.evidence,
            "source": self.source,
        }


@dataclass(frozen=True)
class AgentVerdict:
    """Sealed output of the agent layer. Constructed only via agents.boundary.seal_verdict."""

    document: str
    status: InvoiceStatus
    flags: tuple[Flag, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.status, InvoiceStatus):
            raise TypeError(f"Agent verdict status must be an InvoiceStatus, got {self.status!r}")
        if not all(isinstance(f, Flag) for f in self.flags):
            raise TypeError("Agent verdict flags must be Flag instances")

    @property
    def actionable_flags(self) -> tuple[Flag, ...]:
        return tuple(f for f in self.flags if f.severity is not Severity.INFO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "status": self.status.value,
            "flags": [f.to_dict() for f in self.flags],
        }
