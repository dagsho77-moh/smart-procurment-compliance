"""Shared helpers for deterministic checks. Every check returns list[Flag] and never decides."""

from __future__ import annotations

from decimal import Decimal

from invoice_guard.models.findings import Category, Flag, Severity


def flag(check: str, category: Category, severity: Severity, message: str, **evidence) -> Flag:
    return Flag(
        check=check,
        category=category,
        severity=severity,
        message=message,
        evidence={k: (str(v) if isinstance(v, Decimal) else v) for k, v in evidence.items()},
    )


def money(value: Decimal, currency: str = "SAR") -> str:
    return f"{currency} {value:,.2f}"
