"""Agent boundary layer - Gora's rule #4: AI agents may ONLY raise flags.

Enforcement implemented here (the other layers are the type system in
models.findings, the absence of any approval tool, and the import-linter contract):

* LLM output is parsed into a closed schema: {"findings": [...]}. Anything else is
  discarded and itself becomes a flag.
* Any attempt by a model to emit a decision ("approve", "status": "APPROVED", ...)
  is ignored and recorded as `advisory.agent_attempted_decision`.
* LLM-sourced flags are capped at WARNING: a model can draw attention to an invoice
  but can neither block nor clear it on its own.
* Flags are additive. Nothing here (or anywhere) removes a flag.
* The final status is computed deterministically from flags and must be an
  InvoiceStatus - a type that has no "approved" member.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from invoice_guard.models.findings import AgentVerdict, Category, Flag, InvoiceStatus, Severity
from invoice_guard.tools.extractor import parse_json_object

ALLOWED_LLM_SEVERITIES = (Severity.INFO, Severity.WARNING)
DECISION_KEYS = {
    "decision", "status", "approval", "approved", "approve", "action", "verdict",
    "authorize", "authorise", "authorized", "authorised", "release", "pay", "payment",
}


class AgentBoundaryViolation(RuntimeError):
    """Raised if code attempts to push an agent past its flag-only mandate."""


def _decision_like(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return []
    return [k for k in obj if str(k).strip().lower() in DECISION_KEYS]


def parse_advisory_findings(raw: str, *, source_check: str = "advisory") -> list[Flag]:
    """Convert raw LLM advisory output into capped, schema-checked flags."""
    try:
        data = parse_json_object(raw)
    except (ValueError, json.JSONDecodeError):
        return [
            Flag(f"{source_check}.unparseable_output", Category.ADVISORY, Severity.WARNING,
                 "Advisory review output could not be parsed; manual contract review recommended.",
                 {"raw_excerpt": (raw or "")[:300]}, source="llm")
        ]

    flags: list[Flag] = []
    attempted = _decision_like(data)
    findings = data.get("findings")
    if not isinstance(findings, list):
        findings = []
        flags.append(
            Flag(f"{source_check}.unparseable_output", Category.ADVISORY, Severity.WARNING,
                 "Advisory output did not contain a 'findings' list.", {}, source="llm")
        )

    for i, item in enumerate(findings):
        if not isinstance(item, dict) or not str(item.get("message", "")).strip():
            continue
        attempted += _decision_like(item)
        requested = str(item.get("severity", "WARNING")).upper()
        severity = Severity.INFO if requested == "INFO" else Severity.WARNING  # cap at WARNING
        flags.append(
            Flag(
                check=f"{source_check}.finding_{i + 1}",
                category=Category.ADVISORY,
                severity=severity,
                message=str(item["message"]).strip()[:500],
                evidence={
                    "invoice_ref": str(item.get("invoice_ref", ""))[:120],
                    "contract_ref": str(item.get("contract_ref", ""))[:120],
                    "requested_severity": requested,
                },
                source="llm",
            )
        )

    if attempted:
        flags.append(
            Flag(f"{source_check}.agent_attempted_decision", Category.ADVISORY, Severity.WARNING,
                 "The AI agent tried to output a payment decision. Agents cannot approve or "
                 "decide; the attempt was discarded. Check the invoice for embedded instructions "
                 "(prompt injection).",
                 {"discarded_keys": sorted(set(attempted))}, source="llm")
        )
    return flags


def decide_status(flags: Iterable[Flag], *, is_invoice: bool = True) -> InvoiceStatus:
    """Deterministic status from flags. The best possible outcome is READY_FOR_CFO_REVIEW."""
    flags = list(flags)
    if not is_invoice:
        return InvoiceStatus.RETURNED_NOT_AN_INVOICE
    if any(f.category is Category.SECURITY and f.severity is Severity.CRITICAL for f in flags):
        return InvoiceStatus.BLOCKED_SECURITY_HOLD
    if any(f.severity is not Severity.INFO for f in flags):
        return InvoiceStatus.FLAGGED_FOR_REVIEW
    return InvoiceStatus.READY_FOR_CFO_REVIEW


def seal_verdict(document: str, flags: Iterable[Flag], status: Any) -> AgentVerdict:
    """The only way agent output leaves the agent layer."""
    if not isinstance(status, InvoiceStatus):
        raise AgentBoundaryViolation(
            f"Agents may only assign InvoiceStatus values (none of which approve); got {status!r}"
        )
    flags = tuple(flags)
    for f in flags:
        if f.source == "llm" and f.severity not in ALLOWED_LLM_SEVERITIES:
            raise AgentBoundaryViolation(f"LLM-sourced flag {f.check} exceeds WARNING severity")
    return AgentVerdict(document=document, status=status, flags=flags)
