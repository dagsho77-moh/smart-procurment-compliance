"""Task Agent - the auditor.

Tool chain (same order as the Foundry design):
    Classification -> Extraction -> Math Check
then the deterministic checks (security guardrails, duplicates, PO matching,
contract rules, policy) and, optionally, the Knowledge Agent's advisory review.

The agent's toolset is closed and read-only with respect to payments. Its output is
an AgentVerdict sealed by agents.boundary. It has no way to approve anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from invoice_guard.agents.boundary import decide_status, parse_advisory_findings, seal_verdict
from invoice_guard.checks.contract_rules import contract_rules_check, policy_check
from invoice_guard.checks.duplicate_check import duplicate_invoice_check, normalize_invoice_number
from invoice_guard.checks.math_check import math_check_with_tolerance
from invoice_guard.checks.po_matching import po_matching_check
from invoice_guard.checks.security_guardrails import security_guardrails_check
from invoice_guard.config import Settings
from invoice_guard.governance.audit_trail import AuditTrail
from invoice_guard.ingestion.loader import load_document
from invoice_guard.knowledge.knowledge_agent import KnowledgeAgent
from invoice_guard.llm.client import LLMClient
from invoice_guard.llm.prompts import PromptLibrary
from invoice_guard.models.findings import AgentVerdict, Category, Flag, InvoiceStatus, Severity
from invoice_guard.models.invoice import Invoice, Submission
from invoice_guard.models.procurement import MasterData
from invoice_guard.models.rules import RuleSet
from invoice_guard.storage.registry import InvoiceRegistry
from invoice_guard.tools.classifier import DocClass, classify_document
from invoice_guard.tools.extractor import extract_invoice

# Documented, closed toolset. Nothing here can change a payment status.
TOOLS = (
    "classify_document",
    "extract_invoice",
    "math_check_with_tolerance",
    "security_guardrails_check",
    "duplicate_invoice_check",
    "po_matching_check",
    "contract_rules_check",
    "policy_check",
    "knowledge_agent.advisory_review",
)


@dataclass(frozen=True)
class AuditResult:
    verdict: AgentVerdict
    invoice: Invoice | None
    doc_class: DocClass
    file_sha256: str


class TaskAgent:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LLMClient,
        prompts: PromptLibrary,
        master: MasterData,
        registry: InvoiceRegistry,
        rulesets: dict[str, list[RuleSet]],
        trail: AuditTrail,
        knowledge_agent: KnowledgeAgent | None = None,
    ):
        self.s, self.llm, self.prompts = settings, llm, prompts
        self.master, self.registry, self.rulesets = master, registry, rulesets
        self.trail, self.knowledge_agent = trail, knowledge_agent

    def audit(self, submission: Submission) -> AuditResult:
        path = Path(submission.file_path)
        ref = path.name
        source_path = str(path.resolve())
        flags: list[Flag] = []

        doc = load_document(path, self.s.ingestion, render_images=self.llm.needs_images)
        self.trail.event(ref, "ingest", kind=doc.kind, sha256=doc.sha256, text_chars=len(doc.text),
                         pages=len(doc.page_images), sender=submission.sender_email,
                         submitted_by=submission.submitted_by)

        # Tool 1: classification ------------------------------------------------
        doc_class, raw = classify_document(doc, self.llm, self.prompts)
        self.trail.event(ref, "classify", result=doc_class.value, raw=raw[:200],
                         prompt=self.prompts.get("classifier").version, provider=self.llm.provider)
        if doc_class is DocClass.INVALID:
            flags.append(Flag("classification.not_an_invoice", Category.CLASSIFICATION, Severity.INFO,
                              "Document is not an invoice (quotation, statement, contract...). "
                              "Returned to sender.", source="llm"))
            return self._finish(ref, source_path, doc.sha256, None, flags, doc_class)
        if doc_class is DocClass.UNCERTAIN:
            flags.append(Flag("classification.uncertain", Category.CLASSIFICATION, Severity.WARNING,
                              f"Classifier gave an unexpected answer ({raw[:60]!r}); treated as "
                              "invoice for checking, human confirmation needed.", source="llm"))

        # Tool 2: extraction ----------------------------------------------------
        invoice, errors, raw = extract_invoice(doc, self.llm, self.prompts)
        self.trail.event(ref, "extract", ok=invoice is not None, errors=errors,
                         prompt=self.prompts.get("extractor").version,
                         invoice=invoice.to_dict() if invoice else None)
        if invoice is None:
            flags.append(Flag("extraction.failed", Category.EXTRACTION, Severity.CRITICAL,
                              "Could not extract a valid invoice: " + "; ".join(errors)[:400],
                              {"errors": errors}))
            return self._finish(ref, source_path, doc.sha256, None, flags, doc_class)

        # Tool 3: math check + deterministic compliance checks ------------------
        vendor, security_flags = security_guardrails_check(invoice, submission, self.master)
        steps: list[tuple[str, list[Flag]]] = [
            ("security_guardrails", security_flags),
            ("math_check", math_check_with_tolerance(invoice, self.s.vat_rate, self.s.math)),
            ("duplicate_check", duplicate_invoice_check(
                invoice, file_sha256=doc.sha256, source_path=source_path,
                registry=self.registry, cfg=self.s.duplicate)),
            ("po_matching", po_matching_check(
                invoice, vendor=vendor, master=self.master, registry=self.registry,
                cfg=self.s.po, source_path=source_path)),
            ("contract_rules", contract_rules_check(invoice, vendor, self.rulesets)),
            ("policy", policy_check(invoice, self.s.policy)),
        ]
        for name, step_flags in steps:
            self.trail.event(ref, name, flags=[f.to_dict() for f in step_flags])
            flags.extend(step_flags)

        # Knowledge Agent advisory review (LLM, capped, additive) -----------------
        if self.knowledge_agent is not None and vendor is not None and self.s.knowledge.advisory_review:
            raw_advice, passages = self.knowledge_agent.advisory_review(invoice, vendor, doc.sha256)
            advisory = parse_advisory_findings(raw_advice)
            self.trail.event(ref, "advisory_review", passages=[c.citation for c in passages],
                             raw=raw_advice[:500], flags=[f.to_dict() for f in advisory])
            flags.extend(advisory)

        return self._finish(ref, source_path, doc.sha256, invoice, flags, doc_class)

    def _finish(self, ref: str, source_path: str, sha: str, invoice: Invoice | None,
                flags: list[Flag], doc_class: DocClass) -> AuditResult:
        status = decide_status(flags, is_invoice=doc_class is not DocClass.INVALID)
        verdict = seal_verdict(ref, flags, status)
        is_dup = any(f.category is Category.DUPLICATE and f.severity is Severity.CRITICAL for f in flags)
        self.registry.record(
            source_path=source_path,
            file_sha256=sha,
            invoice=invoice,
            invoice_number_norm=normalize_invoice_number(invoice.invoice_number) if invoice else "",
            status=status.value,
            counts_toward_po=(invoice is not None and not is_dup
                              and status is not InvoiceStatus.BLOCKED_SECURITY_HOLD),
            run_id=self.trail.run_id,
        )
        self.trail.event(ref, "verdict", status=status.value, flag_count=len(flags),
                         actionable=len(verdict.actionable_flags))
        return AuditResult(verdict=verdict, invoice=invoice, doc_class=doc_class, file_sha256=sha)
