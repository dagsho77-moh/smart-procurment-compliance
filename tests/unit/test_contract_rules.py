import tempfile
from datetime import timedelta
from pathlib import Path

from invoice_guard.checks.contract_rules import contract_rules_check, policy_check
from invoice_guard.models.procurement import Vendor
from invoice_guard.models.rules import RuleValidationError, load_approved_rules
from tests.helpers import make_invoice, settings

S = settings()
RULES = load_approved_rules(S.paths.rules_approved_dir)
NCS = Vendor("V-NCS", "Najd", "300123456700003", (), "X", "NCS-2026")


def run(inv, vendor=NCS):
    return {f.check for f in contract_rules_check(inv, vendor, RULES)}


def test_repository_rules_load_and_cite_sources():
    assert set(RULES) == {"V-NCS", "V-RSO", "V-HFM"}
    for rulesets in RULES.values():
        for rs in rulesets:
            assert rs.reviewed_by
            assert all(r.source.get("clause") for r in rs.rules)


def test_compliant_invoice():
    assert run(make_invoice()) == set()


def test_free_shipping_violation_with_evidence():
    flags = contract_rules_check(make_invoice(shipping="500.00"), NCS, RULES)
    assert [f.check for f in flags] == ["contract.free_shipping"]
    assert flags[0].evidence["contract_ref"] == "NCS-2026 §4.2, p.15"


def test_payment_terms_violation():
    inv = make_invoice()
    inv = type(inv)(**{**inv.__dict__, "due_date": inv.invoice_date + timedelta(days=15)})
    assert run(inv) == {"contract.payment_terms"}


def test_unit_price_cap():
    assert run(make_invoice(lines=(("LAP-14-PRO", 1, "6000.00"),))) == {"contract.laptop_price_cap"}


def test_vendor_without_rules_is_flagged():
    other = Vendor("V-NEW", "New", "3", (), "X")
    assert run(make_invoice(), other) == {"contract.no_approved_rules"}


def test_draft_or_unreviewed_rules_are_refused():
    d = Path(tempfile.mkdtemp())
    (d / "x.yaml").write_text("status: DRAFT\nvendor_id: V\ncontract_id: C\n"
                              "effective_from: 2026-01-01\neffective_to: 2026-12-31\nrules: []\n")
    try:
        load_approved_rules(d)
        raise AssertionError("draft rules must not load")
    except RuleValidationError:
        pass
    (d / "x.yaml").write_text("status: APPROVED\nvendor_id: V\ncontract_id: C\n"
                              "effective_from: 2026-01-01\neffective_to: 2026-12-31\nrules: []\n")
    try:
        load_approved_rules(d)
        raise AssertionError("unreviewed rules must not load")
    except RuleValidationError:
        pass


def test_policy_preapproval_threshold():
    big = make_invoice(lines=(("SVC", 6, "1800.00"),), po_number=None)
    assert [f.check for f in policy_check(big, S.policy)] == ["policy.preapproval_required"]
    assert policy_check(make_invoice(po_number=None), S.policy) == []
