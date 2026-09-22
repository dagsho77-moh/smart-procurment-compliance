"""Governed workflow: submit -> Task Agent (classify, extract, check) -> Knowledge Agent
(advisory) -> sealed verdict -> CFO report. Ends at READY_FOR_CFO_REVIEW at best."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from invoice_guard.agents.boundary import seal_verdict
from invoice_guard.agents.task_agent import AuditResult, TaskAgent
from invoice_guard.config import Settings
from invoice_guard.governance.audit_trail import AuditTrail
from invoice_guard.governance.report import write_reports
from invoice_guard.ingestion.loader import SUPPORTED_SUFFIXES
from invoice_guard.knowledge.indexer import build_index
from invoice_guard.knowledge.knowledge_agent import KnowledgeAgent
from invoice_guard.knowledge.retriever import BM25Retriever
from invoice_guard.llm.client import LLMClient, LLMError, create_llm_client
from invoice_guard.llm.prompts import PromptLibrary
from invoice_guard.models.findings import AgentVerdict, Category, Flag, InvoiceStatus, Severity
from invoice_guard.models.invoice import Submission
from invoice_guard.models.procurement import MasterData
from invoice_guard.models.rules import load_approved_rules
from invoice_guard.storage.registry import InvoiceRegistry


@dataclass
class RunSummary:
    run_id: str
    results: list[AuditResult] = field(default_factory=list)
    verdicts: list[AgentVerdict] = field(default_factory=list)
    report_html: Path | None = None
    report_json: Path | None = None
    trace_file: Path | None = None
    aborted_reason: str | None = None


def discover(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    return sorted(p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES)


def load_submissions_metadata(folder: Path) -> dict[str, dict]:
    """Optional intake metadata (sender address etc.), as an AP mailbox would provide."""
    meta = folder / "submissions.json"
    return json.loads(meta.read_text("utf-8")) if meta.exists() else {}


def build_knowledge_agent(settings: Settings, llm: LLMClient, prompts: PromptLibrary) -> KnowledgeAgent:
    # Rebuilt every run (milliseconds) so edited contracts are never served from a stale index.
    sources = [settings.paths.contracts_raw_dir, settings.paths.policies_dir]
    chunks = build_index(sources, settings.paths.index_file)
    return KnowledgeAgent(BM25Retriever(chunks), llm, prompts, settings.knowledge.top_k)


def run_pipeline(
    settings: Settings,
    input_path: Path,
    *,
    sender: str | None = None,
    submitted_by: str | None = None,
    reset_registry: bool = False,
    llm: LLMClient | None = None,
    quiet: bool = False,
) -> RunSummary:
    llm = llm or create_llm_client(settings)
    prompts = PromptLibrary(settings.paths.prompts_dir)
    registry = InvoiceRegistry(settings.paths.registry_db)
    if reset_registry:
        registry.reset()
    trail = AuditTrail(settings.paths.traces_dir)
    knowledge = build_knowledge_agent(settings, llm, prompts) if settings.knowledge.advisory_review else None
    agent = TaskAgent(
        settings=settings, llm=llm, prompts=prompts,
        master=MasterData.load(settings.paths.master_dir), registry=registry,
        rulesets=load_approved_rules(settings.paths.rules_approved_dir),
        trail=trail, knowledge_agent=knowledge,
    )

    summary = RunSummary(run_id=trail.run_id, trace_file=trail.path)
    folder = input_path if input_path.is_dir() else input_path.parent
    metadata = load_submissions_metadata(folder)
    invoices: dict[str, dict | None] = {}
    try:
        for path in discover(input_path):
            meta = metadata.get(path.name, {})
            submission = Submission(
                file_path=str(path),
                sender_email=sender or meta.get("sender_email"),
                submitted_by=submitted_by or meta.get("submitted_by"),
            )
            try:
                result = agent.audit(submission)
            except LLMError as exc:  # quota / connectivity: stop cleanly, keep results so far
                summary.aborted_reason = str(exc)
                trail.event(path.name, "aborted", error=str(exc))
                if not quiet:
                    print(f"\nStopped before {path.name}: {exc}")
                break
            except Exception as exc:  # one bad file must never stop the batch
                trail.event(path.name, "error", error=repr(exc))
                verdict = seal_verdict(path.name, [Flag(
                    "pipeline.error", Category.PIPELINE, Severity.CRITICAL,
                    f"Processing failed: {exc}. Manual handling required.")],
                    InvoiceStatus.FLAGGED_FOR_REVIEW)
                summary.verdicts.append(verdict)
                invoices[path.name] = None
                if not quiet:
                    _print_line(verdict)
                continue
            summary.results.append(result)
            summary.verdicts.append(result.verdict)
            invoices[path.name] = result.invoice.to_dict() if result.invoice else None
            if not quiet:
                _print_line(result.verdict)
    finally:
        registry.close()

    summary.report_html, summary.report_json = write_reports(
        trail.run_id, summary.verdicts, invoices, settings.paths.reports_dir, llm.provider)
    if not quiet:
        print(f"\nTraces:  {trail.path}\nReport:  {summary.report_html}")
        print("Reminder: no invoice has been approved. Decisions require `invoice_guard review` (CFO).")
    return summary


def _print_line(v: AgentVerdict) -> None:
    worst = sorted(v.actionable_flags, key=lambda f: -f.severity.rank)
    detail = ", ".join(f"{f.severity.value} {f.check}" for f in worst[:3]) or "no actionable flags"
    if len(worst) > 3:
        detail += f" (+{len(worst) - 3} more)"
    print(f"{v.document:<42} {v.status.value:<24} {detail}")
