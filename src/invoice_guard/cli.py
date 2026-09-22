"""Command-line interface: python -m invoice_guard <command>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from invoice_guard.config import load_settings


def cmd_synth(args, s) -> int:
    from invoice_guard.synthetic.generator import generate

    manifest = generate(s.paths.synthetic_dir, s.paths.master_dir, clean_count=args.count, seed=args.seed)
    print(f"Generated {len(manifest['cases'])} documents in {s.paths.synthetic_dir}")
    print(f"Master data (vendors, POs, goods receipts) written to {s.paths.master_dir}")
    return 0


def cmd_index(args, s) -> int:
    from invoice_guard.knowledge.indexer import build_index

    chunks = build_index([s.paths.contracts_raw_dir, s.paths.policies_dir], s.paths.index_file)
    print(f"Indexed {len(chunks)} clauses into {s.paths.index_file}")
    return 0


def cmd_compile(args, s) -> int:
    from invoice_guard.knowledge.rule_compiler import draft_rules_for_contract
    from invoice_guard.llm.client import create_llm_client
    from invoice_guard.llm.prompts import PromptLibrary

    llm, prompts = create_llm_client(s), PromptLibrary(s.paths.prompts_dir)
    for path in sorted(s.paths.contracts_raw_dir.glob("*.md")):
        out = draft_rules_for_contract(path, llm, prompts, s.paths.rules_draft_dir)
        print(f"Drafted {out}")
    print("\nDrafts are NOT used until a human reviews them, sets reviewed_by + status: APPROVED,\n"
          f"and moves them to {s.paths.rules_approved_dir}")
    return 0


def cmd_process(args, s) -> int:
    from invoice_guard.workflow.pipeline import run_pipeline

    summary = run_pipeline(s, Path(args.path), sender=args.sender, submitted_by=args.submitted_by,
                           reset_registry=args.reset)
    if summary.aborted_reason:
        return 3
    return 0 if summary.verdicts else 1


def cmd_ask(args, s) -> int:
    from invoice_guard.llm.client import create_llm_client
    from invoice_guard.llm.prompts import PromptLibrary
    from invoice_guard.workflow.pipeline import build_knowledge_agent

    llm = create_llm_client(s)
    agent = build_knowledge_agent(s, llm, PromptLibrary(s.paths.prompts_dir))
    answer, sources = agent.answer(args.question)
    print(answer)
    if sources:
        print("\nSources: " + "; ".join(c.citation for c in sources))
    return 0


def cmd_review(args, s) -> int:
    # The human gate is imported ONLY here, in the human-facing CLI.
    from invoice_guard.governance.human_review import HumanDecision, ReviewError, record_decision

    decision = HumanDecision.APPROVED_BY_HUMAN if args.decision == "approve" else HumanDecision.REJECTED_BY_HUMAN
    try:
        rec = record_decision(s, invoice_number=args.invoice_number, reviewer=args.reviewer,
                              decision=decision, note=args.note or "",
                              acknowledge_security_hold=args.acknowledge_security_hold)
    except ReviewError as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    print(f"Recorded {rec.decision.value} for {rec.invoice_number} by {rec.reviewer} at {rec.decided_at}")
    return 0


def cmd_status(args, s) -> int:
    from invoice_guard.storage.registry import InvoiceRegistry

    reg = InvoiceRegistry(s.paths.registry_db)
    for r in reg.all_records():
        print(f"{Path(r.source_path).name:<42} {r.invoice_number or '-':<18} {r.status}")
    reg.close()
    return 0


def cmd_evaluate(args, s) -> int:
    from invoice_guard.evaluation import evaluate

    result = evaluate(s)
    if args.fail_under is not None and result["score"] < args.fail_under:
        print(f"Score {result['score']:.3f} is below --fail-under {args.fail_under}", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="invoice_guard",
                                description="Local invoice compliance auditing. Flags only - never approves.")
    p.add_argument("--provider", choices=["github", "ollama", "mock"], help="override LLM_PROVIDER")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("synth", help="generate synthetic invoices and master data")
    sp.add_argument("--count", type=int, default=8, help="number of clean invoices (min 4)")
    sp.add_argument("--seed", type=int, default=42)
    sp.set_defaults(func=cmd_synth)

    sub.add_parser("index", help="index contracts and policies for the Knowledge Agent").set_defaults(func=cmd_index)
    sub.add_parser("compile-contracts", help="LLM-draft executable rules from contracts (for human review)"
                   ).set_defaults(func=cmd_compile)

    sp = sub.add_parser("process", help="audit a file or folder of invoices")
    sp.add_argument("path")
    sp.add_argument("--sender", help="sender email for single-file runs")
    sp.add_argument("--submitted-by", help="internal user submitting the invoice(s)")
    sp.add_argument("--reset", action="store_true", help="clear the invoice registry first")
    sp.set_defaults(func=cmd_process)

    sp = sub.add_parser("ask", help="ask the Knowledge Agent about contracts/policies")
    sp.add_argument("question")
    sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("review", help="HUMAN payment decision (CFO role only)")
    sp.add_argument("invoice_number")
    sp.add_argument("--reviewer", required=True)
    sp.add_argument("--decision", required=True, choices=["approve", "reject"])
    sp.add_argument("--note")
    sp.add_argument("--acknowledge-security-hold", action="store_true")
    sp.set_defaults(func=cmd_review)

    sub.add_parser("status", help="list audited documents").set_defaults(func=cmd_status)

    sp = sub.add_parser("evaluate", help="score the pipeline on synthetic ground truth")
    sp.add_argument("--fail-under", type=float)
    sp.set_defaults(func=cmd_evaluate)
    return p


def main(argv: list[str] | None = None) -> int:
    from invoice_guard.llm.client import LLMError

    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(provider=args.provider)
        return args.func(args, settings)
    except (LLMError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
