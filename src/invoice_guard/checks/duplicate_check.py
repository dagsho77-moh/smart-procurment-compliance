"""Duplicate-invoice detection (Gora's rule #3), three layers:

1. exact file     - identical SHA-256 of the file bytes             -> CRITICAL
2. business key   - same vendor VAT no. + normalised invoice number -> CRITICAL
3. fuzzy          - same vendor, amount within tolerance, dates within N days,
                    similar invoice number                          -> WARNING
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from invoice_guard.checks.base import flag, money
from invoice_guard.config import DuplicateConfig
from invoice_guard.models.findings import Category, Flag, Severity
from invoice_guard.models.invoice import Invoice
from invoice_guard.storage.registry import InvoiceRegistry


def normalize_invoice_number(value: str) -> str:
    """'INV-2026-0012' and 'inv 2026/12' collapse to 'INV202612'.

    Leading zeros are stripped per token *before* separators are removed, so
    'INV-2026-0012' does not turn into the different number 20260012.
    """
    tokens = re.split(r"[^A-Za-z0-9]+", (value or "").upper())
    return "".join(re.sub(r"\d+", lambda m: str(int(m.group())), t) for t in tokens if t)


def duplicate_invoice_check(
    invoice: Invoice,
    *,
    file_sha256: str,
    source_path: str,
    registry: InvoiceRegistry,
    cfg: DuplicateConfig,
) -> list[Flag]:
    flags: list[Flag] = []
    seen: set[int] = set()
    number_norm = normalize_invoice_number(invoice.invoice_number)

    for rec in registry.find_by_hash(file_sha256, exclude_path=source_path):
        seen.add(rec.id)
        flags.append(
            flag(
                "duplicate.exact_file",
                Category.DUPLICATE,
                Severity.CRITICAL,
                f"Identical file already processed as {rec.invoice_number or rec.source_path}.",
                matched_document=rec.source_path,
                matched_invoice_number=rec.invoice_number,
                matched_status=rec.status,
            )
        )

    for rec in registry.find_by_business_key(invoice.vendor_tax_id, number_norm, exclude_path=source_path):
        if rec.id in seen:
            continue
        seen.add(rec.id)
        flags.append(
            flag(
                "duplicate.business_key",
                Category.DUPLICATE,
                Severity.CRITICAL,
                f"Vendor {invoice.vendor_tax_id} already submitted invoice number "
                f"{rec.invoice_number} (normalised '{number_norm}').",
                invoice_ref="invoice_number",
                matched_document=rec.source_path,
                matched_invoice_number=rec.invoice_number,
                matched_status=rec.status,
            )
        )

    for rec in registry.find_by_vendor(invoice.vendor_tax_id, exclude_path=source_path):
        if rec.id in seen or rec.invoice_date is None:
            continue
        amount_diff = abs(rec.total - invoice.total)
        day_gap = abs((rec.invoice_date - invoice.invoice_date).days)
        similarity = SequenceMatcher(None, number_norm, rec.invoice_number_norm).ratio()
        if (
            amount_diff <= cfg.amount_tolerance
            and day_gap <= cfg.fuzzy_date_window_days
            and similarity >= cfg.invoice_number_similarity
        ):
            seen.add(rec.id)
            flags.append(
                flag(
                    "duplicate.suspected",
                    Category.DUPLICATE,
                    Severity.WARNING,
                    f"Looks like a resubmission of {rec.invoice_number}: same amount "
                    f"{money(invoice.total, invoice.currency)}, {day_gap} day(s) apart, "
                    f"invoice number similarity {similarity:.2f}.",
                    matched_document=rec.source_path,
                    matched_invoice_number=rec.invoice_number,
                    similarity=round(similarity, 3),
                    day_gap=day_gap,
                )
            )
    return flags
