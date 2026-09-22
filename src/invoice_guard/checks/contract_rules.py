"""Deterministic contract-rule engine (Gora's rule #1) and internal policy checks.

Only human-approved rule files are evaluated. The LLM never judges compliance itself.
"""

from __future__ import annotations

from decimal import Decimal

from invoice_guard.checks.base import money
from invoice_guard.config import PolicyConfig
from invoice_guard.models.findings import Category, Flag, Severity
from invoice_guard.models.invoice import Invoice, to_decimal
from invoice_guard.models.procurement import Vendor
from invoice_guard.models.rules import ContractRule, RuleSet


def _evidence(rule: ContractRule, ruleset: RuleSet, invoice_ref: str) -> dict:
    return {
        "invoice_ref": invoice_ref,
        "contract_ref": f"{ruleset.contract_id} {rule.contract_ref}",
        "contract_text": rule.source.get("text"),
        "rule_id": rule.id,
    }


def evaluate_rule(rule: ContractRule, ruleset: RuleSet, invoice: Invoice) -> Flag | None:
    p, cur = rule.params, invoice.currency
    check = f"contract.{rule.id}"

    if rule.type == "max_charge":
        charged: Decimal = getattr(invoice, p["target"])
        limit = to_decimal(p["max_amount"])
        if charged > limit:
            return Flag(check, Category.CONTRACT, rule.severity,
                        f"{p['target']} of {money(charged, cur)} exceeds contract maximum "
                        f"{money(limit, cur)}.",
                        _evidence(rule, ruleset, p["target"]))

    elif rule.type == "payment_terms_days":
        expected = int(p["expected_days"])
        if invoice.due_date is None:
            return Flag(check, Category.CONTRACT, Severity.INFO,
                        f"No due date on invoice; contract terms are {expected} days.",
                        _evidence(rule, ruleset, "due_date"))
        actual = (invoice.due_date - invoice.invoice_date).days
        if actual < expected:
            return Flag(check, Category.CONTRACT, rule.severity,
                        f"Invoice demands payment in {actual} days; contract allows {expected} days.",
                        _evidence(rule, ruleset, "due_date"))

    elif rule.type == "unit_price_cap":
        cap = to_decimal(p["max_unit_price"])
        for i, line in enumerate(invoice.line_items):
            if line.sku == p["sku"] and line.unit_price > cap:
                return Flag(check, Category.CONTRACT, rule.severity,
                            f"{line.sku} billed at {money(line.unit_price, cur)}, above contract "
                            f"cap {money(cap, cur)}.",
                            _evidence(rule, ruleset, f"line_items[{i}].unit_price"))

    elif rule.type == "currency":
        if invoice.currency != str(p["expected"]).upper():
            return Flag(check, Category.CONTRACT, rule.severity,
                        f"Invoice currency {invoice.currency}; contract requires {p['expected']}.",
                        _evidence(rule, ruleset, "currency"))
    return None


def contract_rules_check(
    invoice: Invoice, vendor: Vendor | None, rulesets_by_vendor: dict[str, list[RuleSet]]
) -> list[Flag]:
    if vendor is None:
        return []  # unknown vendor is already a CRITICAL security flag
    active = [rs for rs in rulesets_by_vendor.get(vendor.vendor_id, []) if rs.is_effective(invoice.invoice_date)]
    if not active:
        return [
            Flag("contract.no_approved_rules", Category.CONTRACT, Severity.WARNING,
                 f"No human-approved contract rules in force for {vendor.name} on "
                 f"{invoice.invoice_date.isoformat()}; contract compliance not verified.",
                 {"vendor_id": vendor.vendor_id})
        ]
    flags = []
    for ruleset in active:
        for rule in ruleset.rules:
            result = evaluate_rule(rule, ruleset, invoice)
            if result is not None:
                flags.append(result)
    return flags


def policy_check(invoice: Invoice, cfg: PolicyConfig) -> list[Flag]:
    """Internal spending policy: high-value invoices need prior authorisation (a PO)."""
    if invoice.po_number is None and invoice.total > cfg.preapproval_required_above:
        return [
            Flag("policy.preapproval_required", Category.POLICY, Severity.WARNING,
                 f"Invoice total {money(invoice.total, invoice.currency)} exceeds "
                 f"{money(cfg.preapproval_required_above, invoice.currency)} without a PO / prior "
                 f"authorisation.",
                 {"invoice_ref": "total", "policy_ref": "Procurement Policy §3.1"})
        ]
    return []
