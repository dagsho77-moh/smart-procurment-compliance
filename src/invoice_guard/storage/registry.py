"""Local SQLite registry of processed invoices (history for duplicate & PO checks).

Read/record access only. Human payment decisions are NOT written here; they are
stored by governance.human_review, which AI layers cannot import.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from invoice_guard.models.invoice import Invoice

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    file_sha256 TEXT NOT NULL,
    vendor_tax_id TEXT,
    invoice_number TEXT,
    invoice_number_norm TEXT,
    invoice_date TEXT,
    total TEXT,
    currency TEXT,
    po_number TEXT,
    status TEXT NOT NULL,
    counts_toward_po INTEGER NOT NULL DEFAULT 1,
    run_id TEXT,
    processed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_inv_hash ON invoices(file_sha256);
CREATE INDEX IF NOT EXISTS ix_inv_key ON invoices(vendor_tax_id, invoice_number_norm);
CREATE TABLE IF NOT EXISTS invoice_lines (
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    po_number TEXT,
    sku TEXT,
    quantity TEXT,
    unit_price TEXT
);
CREATE TABLE IF NOT EXISTS human_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_record_id INTEGER NOT NULL,
    invoice_number TEXT NOT NULL,
    decision TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    note TEXT,
    decided_at TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class InvoiceRecord:
    id: int
    source_path: str
    file_sha256: str
    vendor_tax_id: str
    invoice_number: str
    invoice_number_norm: str
    invoice_date: date | None
    total: Decimal
    po_number: str | None
    status: str


class InvoiceRegistry:
    def __init__(self, db_path: Path | str):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def reset(self) -> None:
        with self._conn:
            self._conn.executescript(
                "DELETE FROM invoice_lines; DELETE FROM invoices; DELETE FROM human_decisions;"
            )

    # -- queries -----------------------------------------------------------------
    @staticmethod
    def _to_record(row: sqlite3.Row) -> InvoiceRecord:
        return InvoiceRecord(
            id=row["id"],
            source_path=row["source_path"],
            file_sha256=row["file_sha256"],
            vendor_tax_id=row["vendor_tax_id"] or "",
            invoice_number=row["invoice_number"] or "",
            invoice_number_norm=row["invoice_number_norm"] or "",
            invoice_date=date.fromisoformat(row["invoice_date"]) if row["invoice_date"] else None,
            total=Decimal(row["total"] or "0"),
            po_number=row["po_number"],
            status=row["status"],
        )

    def _select(self, where: str, params: tuple) -> list[InvoiceRecord]:
        rows = self._conn.execute(f"SELECT * FROM invoices WHERE {where} ORDER BY id", params)
        return [self._to_record(r) for r in rows]

    def find_by_hash(self, sha256: str, exclude_path: str) -> list[InvoiceRecord]:
        return self._select("file_sha256 = ? AND source_path != ?", (sha256, exclude_path))

    def find_by_business_key(self, tax_id: str, number_norm: str, exclude_path: str) -> list[InvoiceRecord]:
        return self._select(
            "vendor_tax_id = ? AND invoice_number_norm = ? AND source_path != ?",
            (tax_id, number_norm, exclude_path),
        )

    def find_by_vendor(self, tax_id: str, exclude_path: str) -> list[InvoiceRecord]:
        return self._select("vendor_tax_id = ? AND source_path != ?", (tax_id, exclude_path))

    def find_by_invoice_number(self, invoice_number: str) -> list[InvoiceRecord]:
        return self._select("invoice_number = ?", (invoice_number,))

    def all_records(self) -> list[InvoiceRecord]:
        return self._select("1 = 1", ())

    def invoiced_quantity(self, po_number: str, sku: str, exclude_path: str) -> Decimal:
        rows = self._conn.execute(
            """SELECT l.quantity FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
               WHERE l.po_number = ? AND l.sku = ? AND i.counts_toward_po = 1 AND i.source_path != ?""",
            (po_number, sku, exclude_path),
        )
        return sum((Decimal(r["quantity"]) for r in rows), Decimal("0"))

    def invoiced_value(self, po_number: str, exclude_path: str) -> Decimal:
        rows = self._conn.execute(
            """SELECT l.quantity, l.unit_price FROM invoice_lines l JOIN invoices i ON i.id = l.invoice_id
               WHERE l.po_number = ? AND i.counts_toward_po = 1 AND i.source_path != ?""",
            (po_number, exclude_path),
        )
        return sum((Decimal(r["quantity"]) * Decimal(r["unit_price"]) for r in rows), Decimal("0"))

    # -- writes ------------------------------------------------------------------
    def record(
        self,
        *,
        source_path: str,
        file_sha256: str,
        invoice: Invoice | None,
        invoice_number_norm: str,
        status: str,
        counts_toward_po: bool,
        run_id: str,
    ) -> int:
        """Record an audited document. Re-processing the same path replaces the old record."""
        with self._conn:
            self._conn.execute("DELETE FROM invoices WHERE source_path = ?", (source_path,))
            cur = self._conn.execute(
                """INSERT INTO invoices (source_path, file_sha256, vendor_tax_id, invoice_number,
                   invoice_number_norm, invoice_date, total, currency, po_number, status,
                   counts_toward_po, run_id, processed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    source_path,
                    file_sha256,
                    invoice.vendor_tax_id if invoice else None,
                    invoice.invoice_number if invoice else None,
                    invoice_number_norm or None,
                    invoice.invoice_date.isoformat() if invoice else None,
                    str(invoice.total) if invoice else None,
                    invoice.currency if invoice else None,
                    invoice.po_number if invoice else None,
                    status,
                    1 if counts_toward_po else 0,
                    run_id,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            record_id = int(cur.lastrowid)
            if invoice and invoice.po_number:
                self._conn.executemany(
                    "INSERT INTO invoice_lines (invoice_id, po_number, sku, quantity, unit_price) VALUES (?,?,?,?,?)",
                    [
                        (record_id, invoice.po_number, li.sku, str(li.quantity), str(li.unit_price))
                        for li in invoice.line_items
                        if li.sku
                    ],
                )
        return record_id
