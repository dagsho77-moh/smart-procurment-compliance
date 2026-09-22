"""CFO report: one self-contained HTML page (plus JSON) per pipeline run."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path

from invoice_guard.models.findings import AgentVerdict, InvoiceStatus

STATUS_COLOURS = {
    InvoiceStatus.BLOCKED_SECURITY_HOLD: "#b42318",
    InvoiceStatus.FLAGGED_FOR_REVIEW: "#b54708",
    InvoiceStatus.READY_FOR_CFO_REVIEW: "#027a48",
    InvoiceStatus.RETURNED_NOT_AN_INVOICE: "#475467",
}


def write_reports(run_id: str, verdicts: list[AgentVerdict], invoices: dict, reports_dir: Path,
                  provider: str) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"run_{run_id}.json"
    json_path.write_text(json.dumps(
        {"run_id": run_id, "provider": provider,
         "results": [v.to_dict() | {"invoice": invoices.get(v.document)} for v in verdicts]},
        indent=2, ensure_ascii=False), "utf-8")

    counts = Counter(v.status for v in verdicts)
    esc = html.escape
    rows = []
    for v in verdicts:
        inv = invoices.get(v.document) or {}
        flag_items = "".join(
            f"<li><b>{esc(f.severity.value)}</b> <code>{esc(f.check)}</code> {esc(f.message)}"
            + (f"<br><small>{esc(json.dumps(f.evidence, ensure_ascii=False))}</small>" if f.evidence else "")
            + "</li>"
            for f in v.flags
        ) or "<li>No findings.</li>"
        rows.append(
            f"<tr><td>{esc(v.document)}</td><td>{esc(inv.get('invoice_number') or '-')}</td>"
            f"<td>{esc(inv.get('vendor_name') or '-')}</td>"
            f"<td style='text-align:right'>{esc(str(inv.get('total') or '-'))}</td>"
            f"<td><span class='pill' style='background:{STATUS_COLOURS[v.status]}'>"
            f"{esc(v.status.value)}</span></td><td><ul>{flag_items}</ul></td></tr>"
        )
    summary = " · ".join(f"{s.value}: {counts.get(s, 0)}" for s in InvoiceStatus)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Invoice Guard - CFO review {esc(run_id)}</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;color:#101828}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #eaecf0;padding:.6rem;vertical-align:top;text-align:left}}
th{{background:#f9fafb}}.pill{{color:#fff;padding:.15rem .5rem;border-radius:999px;font-size:.8rem;white-space:nowrap}}
.banner{{background:#fef3f2;border:1px solid #fecdca;padding:.8rem 1rem;border-radius:8px;margin:1rem 0}}
ul{{margin:0;padding-left:1.1rem}}small{{color:#475467}}code{{font-size:.85em}}
</style></head><body>
<h1>Invoice Guard - CFO review package</h1>
<p>Run <code>{esc(run_id)}</code> · LLM provider: <code>{esc(provider)}</code></p>
<div class="banner"><b>Nothing in this report is a payment approval.</b> AI agents only raise flags.
Payment decisions are recorded by the CFO with <code>python -m invoice_guard review</code>.</div>
<p>{esc(summary)}</p>
<table><thead><tr><th>Document</th><th>Invoice #</th><th>Vendor</th><th>Total</th><th>Status</th><th>Findings &amp; evidence</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></body></html>"""
    html_path = reports_dir / f"cfo_report_{run_id}.html"
    html_path.write_text(page, "utf-8")
    return html_path, json_path
