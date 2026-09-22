from invoice_guard.checks.security_guardrails import iban_is_valid, security_guardrails_check
from invoice_guard.models.findings import Severity
from invoice_guard.models.invoice import Submission
from invoice_guard.models.procurement import MasterData, Vendor
from invoice_guard.synthetic.fixtures import saudi_iban
from tests.helpers import make_invoice

IBAN = "SA0380000000608010167519"
VENDOR = Vendor("V-NCS", "Najd", "300123456700003", ("billing@najd.example",), IBAN)
MASTER = MasterData({"V-NCS": VENDOR}, {}, {})
OK = Submission("x.pdf", sender_email="billing@najd.example")


def run(inv, sub=OK):
    vendor, flags = security_guardrails_check(inv, sub, MASTER)
    return vendor, {f.check: f.severity for f in flags}


def test_iban_checksum():
    assert iban_is_valid(IBAN)
    assert iban_is_valid(saudi_iban("10", "000019284756102938"))
    assert not iban_is_valid("SA0480000000608010167519")


def test_clean_invoice_passes():
    vendor, flags = run(make_invoice())
    assert vendor is VENDOR and flags == {}


def test_changed_bank_account_is_critical():
    _, flags = run(make_invoice(iban=saudi_iban("65", "000044419283746510")))
    assert flags == {"security.iban_mismatch": Severity.CRITICAL}


def test_unregistered_sender_is_critical():
    _, flags = run(make_invoice(), Submission("x.pdf", sender_email="attacker@free-mail.example"))
    assert flags == {"security.unregistered_sender": Severity.CRITICAL}


def test_unknown_vendor_is_critical():
    vendor, flags = run(make_invoice(vendor_tax_id="311111111100003"))
    assert vendor is None and flags == {"security.unknown_vendor": Severity.CRITICAL}


def test_bad_vat_number_format_warns():
    _, flags = run(make_invoice(vendor_tax_id="12345"))
    assert flags["security.vat_number_format"] is Severity.WARNING
