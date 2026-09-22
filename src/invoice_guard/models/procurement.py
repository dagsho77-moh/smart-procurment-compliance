"""Master data: vendors, purchase orders, goods receipts."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from invoice_guard.models.invoice import normalize_iban, normalize_tax_id, to_decimal


@dataclass(frozen=True)
class Vendor:
    vendor_id: str
    name: str
    tax_id: str
    registered_emails: tuple[str, ...]
    iban: str
    contract_id: str | None = None


@dataclass(frozen=True)
class POLine:
    sku: str
    description: str
    quantity: Decimal
    unit_price: Decimal


@dataclass(frozen=True)
class PurchaseOrder:
    po_number: str
    vendor_id: str
    status: str  # OPEN | CLOSED | CANCELLED
    lines: tuple[POLine, ...]

    @property
    def total_value(self) -> Decimal:
        return sum((ln.quantity * ln.unit_price for ln in self.lines), Decimal("0"))

    def line_for(self, sku: str) -> POLine | None:
        return next((ln for ln in self.lines if ln.sku == sku), None)


@dataclass(frozen=True)
class GoodsReceipt:
    grn_number: str
    po_number: str
    received: dict[str, Decimal]  # sku -> quantity received


@dataclass
class MasterData:
    vendors: dict[str, Vendor]
    purchase_orders: dict[str, PurchaseOrder]
    receipts_by_po: dict[str, list[GoodsReceipt]]

    @classmethod
    def load(cls, master_dir: Path) -> MasterData:
        def read(name: str) -> list[dict]:
            p = master_dir / name
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

        vendors = {
            v["vendor_id"]: Vendor(
                vendor_id=v["vendor_id"],
                name=v["name"],
                tax_id=normalize_tax_id(v["tax_id"]),
                registered_emails=tuple(e.lower() for e in v["registered_emails"]),
                iban=normalize_iban(v["iban"]),
                contract_id=v.get("contract_id"),
            )
            for v in read("vendors.json")
        }
        pos = {
            po["po_number"]: PurchaseOrder(
                po_number=po["po_number"],
                vendor_id=po["vendor_id"],
                status=po["status"].upper(),
                lines=tuple(
                    POLine(
                        sku=ln["sku"],
                        description=ln["description"],
                        quantity=to_decimal(ln["quantity"]),
                        unit_price=to_decimal(ln["unit_price"]),
                    )
                    for ln in po["lines"]
                ),
            )
            for po in read("purchase_orders.json")
        }
        receipts: dict[str, list[GoodsReceipt]] = defaultdict(list)
        for gr in read("goods_receipts.json"):
            receipts[gr["po_number"]].append(
                GoodsReceipt(
                    grn_number=gr["grn_number"],
                    po_number=gr["po_number"],
                    received={ln["sku"]: to_decimal(ln["quantity"]) for ln in gr["lines"]},
                )
            )
        return cls(vendors=vendors, purchase_orders=pos, receipts_by_po=dict(receipts))

    def vendor_by_tax_id(self, tax_id: str) -> Vendor | None:
        norm = normalize_tax_id(tax_id)
        return next((v for v in self.vendors.values() if v.tax_id == norm), None)

    def received_quantity(self, po_number: str, sku: str) -> Decimal:
        return sum(
            (gr.received.get(sku, Decimal("0")) for gr in self.receipts_by_po.get(po_number, [])),
            Decimal("0"),
        )
