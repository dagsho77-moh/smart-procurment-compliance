"""Evaluate the pipeline against synthetic ground truth (manifest.json).

Scores:
- status accuracy          : automated status matches the expected status
- per-check precision/recall: flags at WARNING+ vs expected flags (advisory.* excluded:
                              LLM-dependent and never decisive)
- extraction field accuracy: extracted values vs truth (meaningful with a real LLM)
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from invoice_guard.config import Settings
from invoice_guard.llm.client import LLMClient
from invoice_guard.models.findings import Severity
from invoice_guard.workflow.pipeline import run_pipeline

FIELDS = ("invoice_number", "vendor_tax_id", "invoice_date", "due_date", "po_number",
          "subtotal", "tax_amount", "total", "iban")


def _norm(field: str, value) -> str:
    if value is None:
        return ""
    if field in {"subtotal", "tax_amount", "total"}:
        return f"{Decimal(str(value)):.2f}"
    return str(value).replace(" ", "").upper()


def evaluate(settings: Settings, synthetic_dir: Path | None = None, *, llm: LLMClient | None = None,
             quiet: bool = False) -> dict:
    synthetic_dir = synthetic_dir or settings.paths.synthetic_dir
    manifest = json.loads((synthetic_dir / "manifest.json").read_text("utf-8"))
    eval_settings = dataclasses.replace(
        settings, paths=dataclasses.replace(settings.paths, runtime_dir=settings.paths.runtime_dir / "eval")
    )
    summary = run_pipeline(eval_settings, synthetic_dir, reset_registry=True, llm=llm, quiet=True)
    verdicts = {v.document: v for v in summary.verdicts}
    extracted = {r.verdict.document: r.invoice for r in summary.results}

    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    status_ok, rows = 0, []
    field_hits = field_total = 0
    for case in manifest["cases"]:
        v = verdicts.get(case["file"])
        actual_status = v.status.value if v else "MISSING"
        allowed = case.get("expected_status_any") or [case["expected_status"]]
        ok = actual_status in allowed
        status_ok += ok
        actual = {f.check for f in (v.flags if v else ())
                  if f.severity is not Severity.INFO and not f.check.startswith("advisory.")}
        expected = set(case["expected_checks"])
        for c in actual & expected:
            counts[c]["tp"] += 1
        for c in actual - expected:
            counts[c]["fp"] += 1
        for c in expected - actual:
            counts[c]["fn"] += 1
        rows.append((case["file"], case["expected_status"], actual_status, ok,
                     sorted(expected - actual), sorted(actual - expected)))

        truth_path = synthetic_dir / "_truth" / f"{Path(case['file']).stem}.json"
        inv = extracted.get(case["file"])
        if inv is not None and truth_path.exists():
            truth = json.loads(truth_path.read_text("utf-8")).get("invoice") or {}
            got = inv.to_dict()
            for fld in FIELDS:
                field_total += 1
                field_hits += _norm(fld, got.get(fld)) == _norm(fld, truth.get(fld))

    tp = sum(c["tp"] for c in counts.values())
    fp = sum(c["fp"] for c in counts.values())
    fn = sum(c["fn"] for c in counts.values())
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    result = {
        "provider": _provider(llm, settings),
        "documents": len(manifest["cases"]),
        "status_accuracy": status_ok / len(manifest["cases"]),
        "check_precision": precision,
        "check_recall": recall,
        "check_f1": f1,
        "extraction_field_accuracy": (field_hits / field_total) if field_total else None,
        "per_check": {k: dict(v) for k, v in sorted(counts.items())},
        "report": str(summary.report_html),
    }
    result["score"] = min(result["status_accuracy"], f1)

    if not quiet:
        print(f"{'document':<42} {'expected':<24} {'actual':<24} ok  missing / unexpected")
        for file, exp, act, ok, missing, extra in rows:
            note = (" missing=" + ",".join(missing) if missing else "") + (" unexpected=" + ",".join(extra) if extra else "")
            print(f"{file:<42} {exp:<24} {act:<24} {'✓' if ok else '✗'} {note}")
        print("\nPer-check results (WARNING+):")
        for name, c in sorted(counts.items()):
            print(f"  {name:<36} tp={c['tp']:<3} fp={c['fp']:<3} fn={c['fn']}")
        fa = result["extraction_field_accuracy"]
        print(f"\nStatus accuracy:  {result['status_accuracy']:.1%}")
        print(f"Check precision:  {precision:.1%}   recall: {recall:.1%}   F1: {f1:.3f}")
        print(f"Extraction field accuracy: {'n/a' if fa is None else f'{fa:.1%}'}")
        print(f"Report: {summary.report_html}")
    return result


def _provider(llm: LLMClient | None, settings: Settings) -> str:
    return llm.provider if llm is not None else settings.llm.provider
