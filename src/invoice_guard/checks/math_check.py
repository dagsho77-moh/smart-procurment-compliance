"""Tool 3 - Math check with rounding tolerance (Gora's rule #2).

Replaces the float-based prototype
    if abs(expected_total - total_calculated) < 0.01
with Decimal arithmetic and a configurable tolerance:
    pass  <=>  |expected - actual| <= min(max_tolerance,
                                          max(absolute_tolerance, relative_tolerance * |expected|))

Levels checked: every line (qty x unit price), subtotal (sum of lines),
VAT ((subtotal + shipping) x rate) and grand total (subtotal + shipping + VAT).
Non-zero differences inside the tolerance are kept as INFO so the trace shows
exactly how much rounding was accepted.
"""

from __future__ import annotations

from decimal import Decimal

from invoice_guard.checks.base import flag, money
from invoice_guard.config import MathConfig
from invoice_guard.models.findings import Category, Flag, Severity
from invoice_guard.models.invoice import Invoice, q2


def tolerance_for(expected: Decimal, cfg: MathConfig) -> Decimal:
    scaled = max(cfg.absolute_tolerance, cfg.relative_tolerance * abs(expected))
    return q2(min(cfg.max_tolerance, scaled))


def compare_amounts(
    *,
    check: str,
    label: str,
    expected: Decimal,
    actual: Decimal,
    tolerance: Decimal,
    severity_if_exceeded: Severity,
    invoice_ref: str,
    currency: str,
) -> Flag | None:
    diff = abs(expected - actual)
    if diff == 0:
        return None
    within = diff <= tolerance
    return flag(
        check=f"math.{check}_rounding" if within else f"math.{check}_mismatch",
        category=Category.MATH,
        severity=Severity.INFO if within else severity_if_exceeded,
        message=(
            f"{label}: rounding difference {money(diff, currency)} accepted (tolerance {money(tolerance, currency)})"
            if within
            else f"{label}: expected {money(expected, currency)} but invoice states "
            f"{money(actual, currency)} (difference {money(diff, currency)} exceeds tolerance "
            f"{money(tolerance, currency)})"
        ),
        invoice_ref=invoice_ref,
        expected=expected,
        actual=actual,
        difference=diff,
        tolerance=tolerance,
    )


def math_check_with_tolerance(invoice: Invoice, vat_rate: Decimal, cfg: MathConfig) -> list[Flag]:
    flags: list[Flag] = []
    cur = invoice.currency

    def add(result: Flag | None) -> None:
        if result is not None:
            flags.append(result)

    # 1. Line level: quantity x unit price = line total
    for i, line in enumerate(invoice.line_items):
        add(
            compare_amounts(
                check="line",
                label=f"Line {i + 1} ({line.description or line.sku})",
                expected=q2(line.quantity * line.unit_price),
                actual=line.line_total,
                tolerance=cfg.line_absolute_tolerance,
                severity_if_exceeded=Severity.WARNING,
                invoice_ref=f"line_items[{i}].line_total",
                currency=cur,
            )
        )

    # 2. Subtotal = sum of stated line totals
    lines_sum = sum((li.line_total for li in invoice.line_items), Decimal("0"))
    add(
        compare_amounts(
            check="subtotal",
            label="Subtotal",
            expected=lines_sum,
            actual=invoice.subtotal,
            tolerance=tolerance_for(lines_sum, cfg),
            severity_if_exceeded=Severity.WARNING,
            invoice_ref="subtotal",
            currency=cur,
        )
    )

    # 3. VAT = (subtotal + shipping) x rate
    expected_tax = q2((invoice.subtotal + invoice.shipping_fee) * vat_rate)
    add(
        compare_amounts(
            check="tax",
            label=f"VAT at {vat_rate * 100:.0f}%",
            expected=expected_tax,
            actual=invoice.tax_amount,
            tolerance=tolerance_for(expected_tax, cfg),
            severity_if_exceeded=Severity.WARNING,
            invoice_ref="tax_amount",
            currency=cur,
        )
    )

    # 4. Grand total = subtotal + shipping + stated VAT
    expected_total = invoice.subtotal + invoice.shipping_fee + invoice.tax_amount
    add(
        compare_amounts(
            check="total",
            label="Invoice total",
            expected=expected_total,
            actual=invoice.total,
            tolerance=tolerance_for(expected_total, cfg),
            severity_if_exceeded=Severity.CRITICAL,
            invoice_ref="total",
            currency=cur,
        )
    )
    return flags
