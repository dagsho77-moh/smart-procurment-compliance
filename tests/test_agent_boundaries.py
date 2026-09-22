"""Gora's rule #4: AI agents may only flag. These tests prove it at every layer."""

import ast
import json
import tempfile
from pathlib import Path

from invoice_guard.agents.boundary import (
    AgentBoundaryViolation,
    decide_status,
    parse_advisory_findings,
    seal_verdict,
)
from invoice_guard.agents.task_agent import TOOLS
from invoice_guard.models.findings import Category, Flag, InvoiceStatus, Severity
from tests.helpers import ROOT, settings

AI_PACKAGES = ["agents", "tools", "checks", "knowledge", "llm", "workflow", "storage"]
PKG = ROOT / "src" / "invoice_guard"


def test_status_type_cannot_express_approval():
    names = [s.name for s in InvoiceStatus] + [s.value for s in InvoiceStatus]
    assert not any("APPROV" in n.upper() or "PAID" in n.upper() for n in names)


def test_seal_verdict_rejects_anything_but_invoice_status():
    for bad in ("APPROVED", "APPROVED_BY_HUMAN", None, 1):
        try:
            seal_verdict("x.pdf", [], bad)
            raise AssertionError(f"accepted {bad!r}")
        except AgentBoundaryViolation:
            pass


def test_llm_flags_cannot_be_critical():
    critical_llm = Flag("advisory.x", Category.ADVISORY, Severity.CRITICAL, "m", source="llm")
    try:
        seal_verdict("x.pdf", [critical_llm], InvoiceStatus.FLAGGED_FOR_REVIEW)
        raise AssertionError("LLM CRITICAL flag accepted")
    except AgentBoundaryViolation:
        pass


def test_model_decision_is_discarded_and_flagged():
    raw = json.dumps({"findings": [], "decision": "APPROVE", "status": "APPROVED"})
    flags = parse_advisory_findings(raw)
    assert [f.check for f in flags] == ["advisory.agent_attempted_decision"]
    assert decide_status(flags) is InvoiceStatus.FLAGGED_FOR_REVIEW


def test_decision_hidden_inside_a_finding_is_also_caught():
    raw = json.dumps({"findings": [{"message": "ok", "severity": "INFO", "approved": True}]})
    assert "advisory.agent_attempted_decision" in {f.check for f in parse_advisory_findings(raw)}


def test_llm_severity_is_capped_at_warning():
    raw = json.dumps({"findings": [{"message": "Shipping charged", "severity": "CRITICAL"}]})
    (flag,) = parse_advisory_findings(raw)
    assert flag.severity is Severity.WARNING and flag.evidence["requested_severity"] == "CRITICAL"


def test_garbage_output_becomes_a_flag_not_a_pass():
    flags = parse_advisory_findings("Sure! This invoice looks approved to me.")
    assert [f.check for f in flags] == ["advisory.unparseable_output"]
    assert decide_status(flags) is InvoiceStatus.FLAGGED_FOR_REVIEW


def test_best_possible_outcome_is_ready_for_cfo_review():
    assert decide_status([]) is InvoiceStatus.READY_FOR_CFO_REVIEW
    info = Flag("math.tax_rounding", Category.MATH, Severity.INFO, "m")
    assert decide_status([info]) is InvoiceStatus.READY_FOR_CFO_REVIEW


def test_security_critical_blocks():
    f = Flag("security.iban_mismatch", Category.SECURITY, Severity.CRITICAL, "m")
    assert decide_status([f]) is InvoiceStatus.BLOCKED_SECURITY_HOLD


def test_agent_toolset_has_no_approval_capability():
    assert not any(word in t.lower() for t in TOOLS for word in ("approv", "pay", "release"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
            mods.update(f"{node.module}.{a.name}" for a in node.names)
    return mods


def test_ai_layers_never_import_the_human_review_gate():
    """Same contract as import-linter in pyproject.toml, checked without extra tools."""
    offenders = []
    for pkg in AI_PACKAGES:
        for path in (PKG / pkg).rglob("*.py"):
            if any("human_review" in m for m in _imports(path)):
                offenders.append(str(path.relative_to(PKG)))
    assert offenders == [], f"AI layers importing the approval gate: {offenders}"
    for module in ("audit_trail", "report", "roles"):  # governance modules AI layers may use
        assert not any("human_review" in m for m in _imports(PKG / "governance" / f"{module}.py"))


def test_human_gate_requires_cfo_and_ack_for_security_hold():
    from invoice_guard.governance.human_review import HumanDecision, ReviewError, record_decision
    from invoice_guard.storage.registry import InvoiceRegistry
    from tests.helpers import make_invoice

    s = settings(tempfile.mkdtemp())
    reg = InvoiceRegistry(s.paths.registry_db)
    reg.record(source_path="/a.pdf", file_sha256="h", invoice=make_invoice(), invoice_number_norm="INV202601",
               status="BLOCKED_SECURITY_HOLD", counts_toward_po=False, run_id="t")
    reg.close()

    def attempt(reviewer, ack=False):
        return record_decision(s, invoice_number="INV-2026-0001", reviewer=reviewer,
                               decision=HumanDecision.APPROVED_BY_HUMAN, acknowledge_security_hold=ack)

    for reviewer, ack in (("procurement.clerk@company.example", True), ("cfo@company.example", False)):
        try:
            attempt(reviewer, ack)
            raise AssertionError("decision should have been refused")
        except ReviewError:
            pass
    rec = attempt("cfo@company.example", ack=True)
    assert rec.decision is HumanDecision.APPROVED_BY_HUMAN and rec.reviewer == "cfo@company.example"
