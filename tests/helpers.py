"""Shared test helpers (plain functions, so tests also run without pytest fixtures)."""

from __future__ import annotations

import dataclasses
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("LLM_PROVIDER", "mock")

from invoice_guard.config import Settings, load_settings  # noqa: E402
from invoice_guard.models.invoice import Invoice, LineItem, q2  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
D = Decimal


def settings(tmp: str | Path | None = None) -> Settings:
    tmp = Path(tmp or tempfile.mkdtemp())
    return load_settings(ROOT, runtime_dir=tmp / "runtime", reports_dir=tmp / "reports", provider="mock")


def with_paths(s: Settings, **paths) -> Settings:
    return dataclasses.replace(s, paths=dataclasses.replace(s.paths, **paths))


def make_invoice(lines=(("SKU-A", 2, "100.00"),), shipping="0", vat="0.15", **overrides) -> Invoice:
    items = tuple(
        LineItem(description=f"Item {sku}", sku=sku, quantity=D(str(q)), unit_price=D(p),
                 line_total=q2(D(str(q)) * D(p)))
        for sku, q, p in lines
    )
    subtotal = sum((li.line_total for li in items), D("0"))
    tax = q2((subtotal + D(shipping)) * D(vat))
    fields = dict(
        invoice_number="INV-2026-0001",
        vendor_name="Najd Computer Supplies Co.",
        vendor_tax_id="300123456700003",
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 4, 30),
        po_number="PO-1",
        currency="SAR",
        line_items=items,
        subtotal=subtotal,
        shipping_fee=D(shipping),
        tax_amount=tax,
        total=subtotal + D(shipping) + tax,
        iban="SA0380000000608010167519",
    )
    fields.update(overrides)
    return Invoice(**fields)
