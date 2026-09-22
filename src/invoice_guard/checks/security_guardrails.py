"""Security guardrails (fraud prevention). A CRITICAL security flag puts the invoice on
BLOCKED_SECURITY_HOLD and raises a security alert:
- invoice from an unknown vendor (VAT number not in vendor master)
- submitted from an email address not registered for the vendor
- bank account (IBAN) differs from the vendor master / contract
"""

from __future__ import annotations

import re

from invoice_guard.checks.base import flag
from invoice_guard.models.findings import Category, Flag, Severity
from invoice_guard.models.invoice import Invoice, Submission, normalize_iban
from invoice_guard.models.procurement import MasterData, Vendor

C = Category.SECURITY
SAUDI_VAT_PATTERN = re.compile(r"^3\d{13}3$")  # 15 digits, starts and ends with 3


def iban_is_valid(iban: str) -> bool:
    """ISO 13616 mod-97 checksum."""
    iban = normalize_iban(iban)
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def security_guardrails_check(
    invoice: Invoice, submission: Submission, master: MasterData
) -> tuple[Vendor | None, list[Flag]]:
    flags: list[Flag] = []
    vendor = master.vendor_by_tax_id(invoice.vendor_tax_id)

    if not SAUDI_VAT_PATTERN.match(invoice.vendor_tax_id):
        flags.append(
            flag("security.vat_number_format", C, Severity.WARNING,
                 f"VAT number {invoice.vendor_tax_id} is not a valid 15-digit Saudi VAT number.",
                 invoice_ref="vendor_tax_id")
        )

    if vendor is None:
        flags.append(
            flag("security.unknown_vendor", C, Severity.CRITICAL,
                 f"No registered vendor with VAT number {invoice.vendor_tax_id} "
                 f"(invoice names '{invoice.vendor_name}').",
                 invoice_ref="vendor_tax_id")
        )
        return None, flags

    sender = (submission.sender_email or "").strip().lower()
    if not sender:
        flags.append(
            flag("security.sender_unknown", C, Severity.WARNING,
                 "Submission has no sender address; sender could not be verified.")
        )
    elif sender not in vendor.registered_emails:
        flags.append(
            flag("security.unregistered_sender", C, Severity.CRITICAL,
                 f"Invoice sent from {sender}, which is not registered for {vendor.name}.",
                 sender=sender, registered=list(vendor.registered_emails))
        )

    if not invoice.iban:
        flags.append(
            flag("security.iban_missing", C, Severity.WARNING,
                 "Invoice shows no bank account; payment details cannot be verified.",
                 invoice_ref="iban")
        )
    else:
        if not iban_is_valid(invoice.iban):
            flags.append(
                flag("security.iban_invalid", C, Severity.CRITICAL,
                     f"IBAN {invoice.iban} fails the checksum.", invoice_ref="iban")
            )
        if normalize_iban(invoice.iban) != vendor.iban:
            flags.append(
                flag("security.iban_mismatch", C, Severity.CRITICAL,
                     f"Bank account on invoice ({invoice.iban}) differs from the account on file "
                     f"for {vendor.name} (ending {vendor.iban[-4:]}). Possible payment fraud.",
                     invoice_ref="iban", contract_ref=vendor.contract_id,
                     on_file_last4=vendor.iban[-4:])
            )
    return vendor, flags
