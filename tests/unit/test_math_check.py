from decimal import Decimal

from invoice_guard.checks.math_check import math_check_with_tolerance, tolerance_for
from invoice_guard.models.findings import Severity
from tests.helpers import make_invoice, settings

S = settings()
VAT = Decimal("0.15")


def checks(flags):
    return {f.check: f.severity for f in flags}


def test_exact_invoice_has_no_findings():
    assert math_check_with_tolerance(make_invoice(), VAT, S.math) == []


def test_decimal_arithmetic_avoids_float_errors():
    # 3 x 0.10 is 0.30000000000000004 in float; must be exactly 0.30 here.
    inv = make_invoice(lines=(("CHEAP", 3, "0.10"),))
    assert math_check_with_tolerance(inv, VAT, S.math) == []


def test_small_rounding_difference_is_info_only():
    inv = make_invoice()
    inv = type(inv)(**{**inv.__dict__, "tax_amount": inv.tax_amount + Decimal("0.02"),
                       "total": inv.total + Decimal("0.02")})
    result = checks(math_check_with_tolerance(inv, VAT, S.math))
    assert result == {"math.tax_rounding": Severity.INFO}


def test_total_mismatch_is_critical():
    inv = make_invoice()
    inv = type(inv)(**{**inv.__dict__, "total": inv.total + Decimal("150")})
    result = checks(math_check_with_tolerance(inv, VAT, S.math))
    assert result == {"math.total_mismatch": Severity.CRITICAL}


def test_line_mismatch_detected():
    inv = make_invoice(lines=(("A", 2, "100.00"), ("B", 1, "50.00")))
    bad = inv.line_items[0].__class__(**{**inv.line_items[0].__dict__, "line_total": Decimal("250.00")})
    inv = type(inv)(**{**inv.__dict__, "line_items": (bad, inv.line_items[1])})
    assert "math.line_mismatch" in checks(math_check_with_tolerance(inv, VAT, S.math))


def test_tolerance_is_capped_for_large_amounts():
    assert tolerance_for(Decimal("10"), S.math) == S.math.absolute_tolerance
    assert tolerance_for(Decimal("50000000"), S.math) == S.math.max_tolerance
    inv = make_invoice(lines=(("BIG", 1000, "9999.99"),))
    inv = type(inv)(**{**inv.__dict__, "total": inv.total + Decimal("2.00")})
    assert checks(math_check_with_tolerance(inv, VAT, S.math)) == {"math.total_mismatch": Severity.CRITICAL}


def test_shipping_is_part_of_the_vat_base():
    inv = make_invoice(shipping="100.00")
    assert math_check_with_tolerance(inv, VAT, S.math) == []
