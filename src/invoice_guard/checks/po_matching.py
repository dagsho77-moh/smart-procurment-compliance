"""Purchase Order matching (Gora's rule #3): three-way match invoice / PO / goods receipt.

Checks: PO exists, belongs to the vendor, is open; each SKU is on the PO; unit price
within tolerance; quantity within ordered-minus-already-invoiced and
received-minus-already-invoiced; invoice subtotal within the PO's remaining balance.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from invoice_guard.checks.base import flag, money
from invoice_guard.config import POConfig
from invoice_guard.models.findings import Category, Flag, Severity
from invoice_guard.models.invoice import Invoice
from invoice_guard.models.procurement import MasterData, Vendor
from invoice_guard.storage.registry import InvoiceRegistry

C = Category.PO_MATCH


def po_matching_check(
    invoice: Invoice,
    *,
    vendor: Vendor | None,
    master: MasterData,
    registry: InvoiceRegistry,
    cfg: POConfig,
    source_path: str,
) -> list[Flag]:
    cur = invoice.currency
    if not invoice.po_number:
        return [
            flag("po.missing_reference", C, Severity.WARNING,
                 "Invoice does not reference a purchase order.", invoice_ref="po_number")
        ]

    po = master.purchase_orders.get(invoice.po_number)
    if po is None:
        return [
            flag("po.not_found", C, Severity.CRITICAL,
                 f"Purchase order {invoice.po_number} does not exist.",
                 invoice_ref="po_number", po_number=invoice.po_number)
        ]

    flags: list[Flag] = []
    if vendor is not None and po.vendor_id != vendor.vendor_id:
        flags.append(
            flag("po.vendor_mismatch", C, Severity.CRITICAL,
                 f"PO {po.po_number} belongs to vendor {po.vendor_id}, not {vendor.vendor_id}.",
                 invoice_ref="po_number", po_vendor=po.vendor_id, invoice_vendor=vendor.vendor_id)
        )
    if po.status != "OPEN":
        flags.append(
            flag("po.not_open", C, Severity.WARNING, f"PO {po.po_number} is {po.status}.",
                 po_number=po.po_number, po_status=po.status)
        )
    has_receipt = bool(master.receipts_by_po.get(po.po_number))
    if cfg.require_goods_receipt and not has_receipt:
        flags.append(
            flag("po.no_goods_receipt", C, Severity.WARNING,
                 f"No goods receipt recorded for PO {po.po_number} (three-way match impossible).",
                 po_number=po.po_number)
        )

    # Aggregate invoiced quantity per SKU (the same SKU may appear on several lines).
    qty_by_sku: dict[str, Decimal] = defaultdict(Decimal)
    first_line: dict[str, int] = {}
    for i, line in enumerate(invoice.line_items):
        if not line.sku:
            flags.append(
                flag("po.line_unmatched", C, Severity.WARNING,
                     f"Line {i + 1} has no SKU and cannot be matched to the PO.",
                     invoice_ref=f"line_items[{i}]")
            )
            continue
        po_line = po.line_for(line.sku)
        if po_line is None:
            flags.append(
                flag("po.sku_not_on_po", C, Severity.WARNING,
                     f"Line {i + 1}: SKU {line.sku} is not on PO {po.po_number}.",
                     invoice_ref=f"line_items[{i}].sku", sku=line.sku)
            )
            continue
        qty_by_sku[line.sku] += line.quantity
        first_line.setdefault(line.sku, i)

        allowed = po_line.unit_price * (1 + cfg.default_price_tolerance_pct / 100)
        if line.unit_price > allowed:
            flags.append(
                flag("po.price_mismatch", C, Severity.WARNING,
                     f"Line {i + 1}: unit price {money(line.unit_price, cur)} exceeds PO price "
                     f"{money(po_line.unit_price, cur)} for {line.sku}.",
                     invoice_ref=f"line_items[{i}].unit_price", po_ref=f"{po.po_number}/{line.sku}",
                     invoice_unit_price=line.unit_price, po_unit_price=po_line.unit_price)
            )

    for sku, qty in qty_by_sku.items():
        po_line = po.line_for(sku)
        assert po_line is not None
        idx = first_line[sku]
        already = registry.invoiced_quantity(po.po_number, sku, exclude_path=source_path)
        remaining_ordered = po_line.quantity - already
        if qty > remaining_ordered + cfg.quantity_tolerance:
            flags.append(
                flag("po.over_invoiced_quantity", C, Severity.WARNING,
                     f"{sku}: invoiced {qty} but only {remaining_ordered} remain on the PO "
                     f"(ordered {po_line.quantity}, already invoiced {already}).",
                     invoice_ref=f"line_items[{idx}].quantity", po_ref=f"{po.po_number}/{sku}",
                     invoiced=qty, ordered=po_line.quantity, previously_invoiced=already)
            )
        if cfg.require_goods_receipt and has_receipt:
            received = master.received_quantity(po.po_number, sku)
            remaining_received = received - already
            if qty > remaining_received + cfg.quantity_tolerance:
                flags.append(
                    flag("po.quantity_exceeds_received", C, Severity.WARNING,
                         f"{sku}: invoiced {qty} but only {remaining_received} received and not yet "
                         f"invoiced (received {received}, already invoiced {already}).",
                         invoice_ref=f"line_items[{idx}].quantity", po_ref=f"{po.po_number}/{sku}",
                         invoiced=qty, received=received, previously_invoiced=already)
                )

    remaining_balance = po.total_value - registry.invoiced_value(po.po_number, exclude_path=source_path)
    if invoice.subtotal > remaining_balance + cfg.balance_tolerance:
        flags.append(
            flag("po.exceeds_remaining_balance", C, Severity.WARNING,
                 f"Invoice subtotal {money(invoice.subtotal, cur)} exceeds remaining PO balance "
                 f"{money(remaining_balance, cur)}.",
                 invoice_ref="subtotal", po_ref=po.po_number,
                 subtotal=invoice.subtotal, remaining_balance=remaining_balance)
        )
    return flags
