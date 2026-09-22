from datetime import timedelta

from invoice_guard.checks.duplicate_check import duplicate_invoice_check, normalize_invoice_number
from invoice_guard.storage.registry import InvoiceRegistry
from tests.helpers import make_invoice, settings

S = settings()


def registry_with(inv, path="/in/a.pdf", sha="h1"):
    reg = InvoiceRegistry(":memory:")
    reg.record(source_path=path, file_sha256=sha, invoice=inv,
               invoice_number_norm=normalize_invoice_number(inv.invoice_number),
               status="READY_FOR_CFO_REVIEW", counts_toward_po=True, run_id="t")
    return reg


def run(inv, reg, path="/in/b.pdf", sha="h2"):
    return {f.check for f in duplicate_invoice_check(
        inv, file_sha256=sha, source_path=path, registry=reg, cfg=S.duplicate)}


def test_normalisation_collapses_formatting_variants():
    assert normalize_invoice_number("INV-2026-0012") == normalize_invoice_number("inv 2026/12")
    assert normalize_invoice_number("INV-2026-0012") != normalize_invoice_number("INV-2026-0120")


def test_exact_file_duplicate():
    inv = make_invoice()
    assert run(inv, registry_with(inv), sha="h1") == {"duplicate.exact_file"}


def test_business_key_duplicate_with_different_formatting():
    inv = make_invoice()
    resubmitted = type(inv)(**{**inv.__dict__, "invoice_number": "inv 2026 0001"})
    assert run(resubmitted, registry_with(inv)) == {"duplicate.business_key"}


def test_fuzzy_duplicate_suspected():
    inv = make_invoice()
    near = type(inv)(**{**inv.__dict__, "invoice_number": "INV-2026-0001-R",
                        "invoice_date": inv.invoice_date + timedelta(days=3)})
    assert run(near, registry_with(inv)) == {"duplicate.suspected"}


def test_different_amount_is_not_a_duplicate():
    inv = make_invoice()
    other = make_invoice(lines=(("SKU-A", 3, "100.00"),), invoice_number="INV-2026-0002")
    assert run(other, registry_with(inv)) == set()


def test_reprocessing_same_file_path_is_not_a_duplicate():
    inv = make_invoice()
    assert run(inv, registry_with(inv), path="/in/a.pdf", sha="h1") == set()
