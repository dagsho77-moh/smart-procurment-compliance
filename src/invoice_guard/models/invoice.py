"""Invoice schema with strict parsing. Money is always Decimal, never float."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")


class InvoiceValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def q2(value: Decimal) -> Decimal:
    """Round to 2 decimals with commercial rounding (ROUND_HALF_UP)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))  # avoid binary float artefacts
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.\-]", "", value.replace(",", ""))
        if cleaned in {"", "-", "."}:
            raise ValueError(f"not a number: {value!r}")
        return Decimal(cleaned)
    raise ValueError(f"not a number: {value!r}")


def normalize_tax_id(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_iban(value: str | None) -> str:
    return re.sub(r"\s", "", value or "").upper()


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal
    sku: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "sku": self.sku,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "line_total": str(self.line_total),
        }


@dataclass(frozen=True)
class Invoice:
    invoice_number: str
    vendor_name: str
    vendor_tax_id: str
    invoice_date: date
    currency: str
    line_items: tuple[LineItem, ...]
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    shipping_fee: Decimal = Decimal("0")
    due_date: date | None = None
    po_number: str | None = None
    iban: str | None = None
    notes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Invoice:
        """Strictly parse extractor output. Collects ALL problems before raising."""
        if not isinstance(data, dict):
            raise InvoiceValidationError(["extractor output is not a JSON object"])
        errors: list[str] = []

        def text(key: str, required: bool = True) -> str | None:
            value = data.get(key)
            if value is None or (isinstance(value, str) and not value.strip()):
                if required:
                    errors.append(f"{key}: missing")
                return None
            return str(value).strip()

        def amount(key: str, required: bool = True, default: Decimal | None = None) -> Decimal:
            value = data.get(key)
            if value is None:
                if required:
                    errors.append(f"{key}: missing")
                return default if default is not None else Decimal("0")
            try:
                return to_decimal(value)
            except (ValueError, InvalidOperation):
                errors.append(f"{key}: not a number ({value!r})")
                return Decimal("0")

        def day(key: str, required: bool = True) -> date | None:
            value = data.get(key)
            if value in (None, ""):
                if required:
                    errors.append(f"{key}: missing")
                return None
            try:
                return date.fromisoformat(str(value)[:10])
            except ValueError:
                errors.append(f"{key}: not an ISO date ({value!r})")
                return None

        lines: list[LineItem] = []
        raw_lines = data.get("line_items")
        if not isinstance(raw_lines, list) or not raw_lines:
            errors.append("line_items: missing or empty")
            raw_lines = []
        for i, item in enumerate(raw_lines):
            if not isinstance(item, dict):
                errors.append(f"line_items[{i}]: not an object")
                continue
            try:
                lines.append(
                    LineItem(
                        description=str(item.get("description") or "").strip(),
                        sku=(str(item["sku"]).strip() or None) if item.get("sku") else None,
                        quantity=to_decimal(item.get("quantity")),
                        unit_price=to_decimal(item.get("unit_price")),
                        line_total=to_decimal(item.get("line_total")),
                    )
                )
            except (ValueError, InvalidOperation) as exc:
                errors.append(f"line_items[{i}]: {exc}")

        invoice_number = text("invoice_number")
        vendor_name = text("vendor_name")
        vendor_tax_id = normalize_tax_id(text("vendor_tax_id"))
        if not vendor_tax_id and "vendor_tax_id: missing" not in errors:
            errors.append("vendor_tax_id: no digits")
        invoice_date = day("invoice_date")
        due_date = day("due_date", required=False)
        subtotal = amount("subtotal")
        tax_amount = amount("tax_amount")
        total = amount("total")
        shipping = amount("shipping_fee", required=False, default=Decimal("0"))
        currency = (text("currency", required=False) or "SAR").upper()

        if errors:
            raise InvoiceValidationError(errors)
        iban = normalize_iban(data.get("iban")) or None
        return cls(
            invoice_number=invoice_number or "",
            vendor_name=vendor_name or "",
            vendor_tax_id=vendor_tax_id,
            invoice_date=invoice_date,  # type: ignore[arg-type]
            due_date=due_date,
            po_number=(str(data["po_number"]).strip() or None) if data.get("po_number") else None,
            currency=currency,
            line_items=tuple(lines),
            subtotal=subtotal,
            shipping_fee=shipping,
            tax_amount=tax_amount,
            total=total,
            iban=iban,
            notes=(str(data["notes"]) if data.get("notes") else None),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_number": self.invoice_number,
            "vendor_name": self.vendor_name,
            "vendor_tax_id": self.vendor_tax_id,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "po_number": self.po_number,
            "currency": self.currency,
            "line_items": [li.to_dict() for li in self.line_items],
            "subtotal": str(self.subtotal),
            "shipping_fee": str(self.shipping_fee),
            "tax_amount": str(self.tax_amount),
            "total": str(self.total),
            "iban": self.iban,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class Submission:
    """How an invoice arrived: file plus intake metadata (e.g. from the AP mailbox)."""

    file_path: str
    sender_email: str | None = None
    submitted_by: str | None = None
