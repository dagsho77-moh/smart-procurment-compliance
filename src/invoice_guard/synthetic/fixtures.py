"""Synthetic vendor fixtures. Contracts in data/contracts/raw and the approved rules in
data/contracts/rules/approved are written to match these values."""

from __future__ import annotations

from decimal import Decimal

D = Decimal

VENDORS = [
    {
        "vendor_id": "V-NCS",
        "name": "Najd Computer Supplies Co.",
        "prefix": "NCS",
        "tax_id": "300123456700003",
        "registered_emails": ["billing@najd-computers.example", "ar@najd-computers.example"],
        "bank_code": "80",
        "account": "000000608010167519",
        "contract_id": "NCS-2026",
        "payment_terms_days": 60,
        "shipping_options": [D("0")],
        "address": "King Fahd Road, Riyadh",
        "catalog": {
            "LAP-14-PRO": ("Laptop 14in Pro, 32GB RAM", D("5200.00")),
            "MON-27-4K": ("Monitor 27in 4K", D("1450.00")),
            "DOCK-USB-C": ("USB-C docking station", D("385.50")),
            "KB-MS-AR": ("Keyboard & mouse set (Arabic layout)", D("129.99")),
            "SSD-1TB": ("NVMe SSD 1TB", D("349.75")),
        },
    },
    {
        "vendor_id": "V-RSO",
        "name": "Red Sea Office Furniture",
        "prefix": "RSO",
        "tax_id": "310987654300003",
        "registered_emails": ["invoices@redsea-furniture.example"],
        "bank_code": "10",
        "account": "000019284756102938",
        "contract_id": "RSO-2026",
        "payment_terms_days": 45,
        "shipping_options": [D("0"), D("150.00")],
        "address": "Tahlia Street, Jeddah",
        "catalog": {
            "CHR-ERGO": ("Ergonomic office chair", D("1150.00")),
            "DSK-160": ("Desk 160cm, oak finish", D("1890.00")),
            "CAB-3D": ("Mobile cabinet, 3 drawers", D("640.25")),
            "TBL-MTG-8": ("Meeting table, 8 seats", D("4275.00")),
        },
    },
    {
        "vendor_id": "V-HFM",
        "name": "Hijaz Facilities Maintenance",
        "prefix": "HFM",
        "tax_id": "302468013500003",
        "registered_emails": ["accounts@hijaz-fm.example"],
        "bank_code": "45",
        "account": "000077310054826193",
        "contract_id": "HFM-2026",
        "payment_terms_days": 30,
        "shipping_options": [D("0")],
        "address": "Al Madinah Road, Jeddah",
        "catalog": {
            "SVC-HVAC-PM": ("HVAC preventive maintenance visit", D("1800.00")),
            "SVC-ELEC-HR": ("Electrician, per hour", D("145.00")),
            "SVC-PLUMB-HR": ("Plumber, per hour", D("135.00")),
            "PRT-FILTER": ("HVAC filter set", D("212.40")),
        },
    },
]

UNKNOWN_VENDOR = {
    "name": "Gulf Premium Trading Est.",
    "tax_id": "311111111100003",
    "bank_code": "20",
    "account": "000055500011122233",
    "address": "Industrial Area, Dammam",
}

BUYER = {"name": "Example Holding Company", "address": "Prince Sultan Road, Jeddah",
         "tax_id": "300000000000003"}
CLERK = "procurement.clerk@company.example"


def saudi_iban(bank_code: str, account: str) -> str:
    """Build a checksum-valid Saudi IBAN (SA + 2 check digits + 2 bank + 18 account)."""
    bban = f"{bank_code}{account}"
    digits = "".join(str(int(ch, 36)) for ch in bban + "SA00")
    check = 98 - int(digits) % 97
    return f"SA{check:02d}{bban}"
