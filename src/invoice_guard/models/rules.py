"""Executable contract rules (Gora's rule #1: contract terms -> structured rules)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from invoice_guard.models.findings import Severity

RULE_TYPES: dict[str, tuple[str, ...]] = {
    # type -> required parameter keys
    "max_charge": ("target", "max_amount"),
    "payment_terms_days": ("expected_days",),
    "unit_price_cap": ("sku", "max_unit_price"),
    "currency": ("expected",),
}
CHARGE_TARGETS = {"shipping_fee"}


class RuleValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ContractRule:
    id: str
    type: str
    severity: Severity
    params: dict[str, Any]
    source: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContractRule:
        rid, rtype = data.get("id"), data.get("type")
        if not rid or rtype not in RULE_TYPES:
            raise RuleValidationError(f"rule {rid!r}: unknown or missing type {rtype!r}")
        missing = [k for k in RULE_TYPES[rtype] if data.get(k) in (None, "")]
        if missing:
            raise RuleValidationError(f"rule {rid!r}: missing parameters {missing}")
        if rtype == "max_charge" and data["target"] not in CHARGE_TARGETS:
            raise RuleValidationError(f"rule {rid!r}: unsupported target {data['target']!r}")
        source = data.get("source") or {}
        if not source.get("clause"):
            raise RuleValidationError(f"rule {rid!r}: must cite a source clause")
        severity = Severity(str(data.get("severity", "WARNING")).upper())
        params = {k: v for k, v in data.items() if k not in {"id", "type", "severity", "source"}}
        return cls(id=str(rid), type=rtype, severity=severity, params=params, source=source)

    @property
    def contract_ref(self) -> str:
        page = self.source.get("page")
        return f"§{self.source.get('clause', '?').lstrip('§')}" + (f", p.{page}" if page else "")


@dataclass(frozen=True)
class RuleSet:
    vendor_id: str
    contract_id: str
    effective_from: date
    effective_to: date
    reviewed_by: str
    rules: tuple[ContractRule, ...] = field(default_factory=tuple)

    def is_effective(self, on: date) -> bool:
        return self.effective_from <= on <= self.effective_to

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, require_review: bool = True) -> RuleSet:
        if require_review and not data.get("reviewed_by"):
            raise RuleValidationError(
                f"{data.get('contract_id')}: approved rule files must name a human 'reviewed_by'"
            )

        def as_date(v: Any) -> date:
            return v if isinstance(v, date) else date.fromisoformat(str(v))

        return cls(
            vendor_id=data["vendor_id"],
            contract_id=data["contract_id"],
            effective_from=as_date(data["effective_from"]),
            effective_to=as_date(data["effective_to"]),
            reviewed_by=data.get("reviewed_by") or "",
            rules=tuple(ContractRule.from_dict(r) for r in data.get("rules", [])),
        )


def load_approved_rules(rules_dir: Path) -> dict[str, list[RuleSet]]:
    """Load ONLY human-approved rule files. Drafts live elsewhere and are never loaded."""
    by_vendor: dict[str, list[RuleSet]] = {}
    for path in sorted(rules_dir.glob("*.y*ml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if (data or {}).get("status", "APPROVED").upper() != "APPROVED":
            raise RuleValidationError(f"{path.name}: only APPROVED rule files may be in this folder")
        ruleset = RuleSet.from_dict(data)
        by_vendor.setdefault(ruleset.vendor_id, []).append(ruleset)
    return by_vendor
