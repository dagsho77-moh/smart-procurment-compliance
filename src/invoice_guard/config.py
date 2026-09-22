"""Settings loading (config/settings.yaml + environment variables)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

try:  # optional convenience
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class MathConfig:
    decimals: int
    absolute_tolerance: Decimal
    relative_tolerance: Decimal
    max_tolerance: Decimal
    line_absolute_tolerance: Decimal


@dataclass(frozen=True)
class DuplicateConfig:
    fuzzy_date_window_days: int
    invoice_number_similarity: float
    amount_tolerance: Decimal


@dataclass(frozen=True)
class POConfig:
    default_price_tolerance_pct: Decimal
    quantity_tolerance: Decimal
    require_goods_receipt: bool
    balance_tolerance: Decimal


@dataclass(frozen=True)
class PolicyConfig:
    preapproval_required_above: Decimal


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    github_endpoint: str
    ollama_endpoint: str
    vision_model: str
    text_model: str
    ollama_vision_model: str
    ollama_text_model: str
    temperature: float
    max_retries: int
    min_seconds_between_calls: float
    request_timeout: float
    cache_responses: bool


@dataclass(frozen=True)
class KnowledgeConfig:
    advisory_review: bool
    top_k: int


@dataclass(frozen=True)
class IngestionConfig:
    max_pages: int
    render_dpi: int
    ocr_enabled: bool
    ocr_languages: str


@dataclass(frozen=True)
class Paths:
    root: Path
    master_dir: Path
    contracts_raw_dir: Path
    rules_draft_dir: Path
    rules_approved_dir: Path
    policies_dir: Path
    synthetic_dir: Path
    runtime_dir: Path
    reports_dir: Path
    prompts_dir: Path
    users_file: Path

    @property
    def registry_db(self) -> Path:
        return self.runtime_dir / "registry.sqlite3"

    @property
    def traces_dir(self) -> Path:
        return self.runtime_dir / "traces"

    @property
    def llm_cache_dir(self) -> Path:
        return self.runtime_dir / "llm_cache"

    @property
    def index_file(self) -> Path:
        return self.runtime_dir / "knowledge_index.json"


@dataclass(frozen=True)
class Settings:
    currency: str
    vat_rate: Decimal
    math: MathConfig
    duplicate: DuplicateConfig
    po: POConfig
    policy: PolicyConfig
    llm: LLMConfig
    knowledge: KnowledgeConfig
    ingestion: IngestionConfig
    paths: Paths


def find_root(start: Path | None = None) -> Path:
    """Project root: $INVOICE_GUARD_ROOT, else the nearest parent containing config/settings.yaml."""
    env_root = os.environ.get("INVOICE_GUARD_ROOT")
    if env_root:
        return Path(env_root).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "settings.yaml").is_file():
            return candidate
    raise FileNotFoundError(
        "Could not find config/settings.yaml. Run from the repository root or set INVOICE_GUARD_ROOT."
    )


def load_settings(
    root: Path | None = None,
    *,
    runtime_dir: Path | None = None,
    reports_dir: Path | None = None,
    provider: str | None = None,
) -> Settings:
    root = (root or find_root()).resolve()
    if load_dotenv is not None:
        load_dotenv(root / ".env", override=False)

    raw = yaml.safe_load((root / "config" / "settings.yaml").read_text(encoding="utf-8"))
    m, d, p, pol = raw["math_check"], raw["duplicate_check"], raw["po_matching"], raw["policy"]
    llm, kn, ing, paths = raw["llm"], raw["knowledge"], raw["ingestion"], raw["paths"]

    def path(key: str) -> Path:
        return (root / paths[key]).resolve()

    env = os.environ.get
    return Settings(
        currency=raw["currency"],
        vat_rate=_dec(raw["vat_rate"]),
        math=MathConfig(
            decimals=int(m["decimals"]),
            absolute_tolerance=_dec(m["absolute_tolerance"]),
            relative_tolerance=_dec(m["relative_tolerance"]),
            max_tolerance=_dec(m["max_tolerance"]),
            line_absolute_tolerance=_dec(m["line_absolute_tolerance"]),
        ),
        duplicate=DuplicateConfig(
            fuzzy_date_window_days=int(d["fuzzy_date_window_days"]),
            invoice_number_similarity=float(d["invoice_number_similarity"]),
            amount_tolerance=_dec(d["amount_tolerance"]),
        ),
        po=POConfig(
            default_price_tolerance_pct=_dec(p["default_price_tolerance_pct"]),
            quantity_tolerance=_dec(p["quantity_tolerance"]),
            require_goods_receipt=bool(p["require_goods_receipt"]),
            balance_tolerance=_dec(p["balance_tolerance"]),
        ),
        policy=PolicyConfig(preapproval_required_above=_dec(pol["preapproval_required_above"])),
        llm=LLMConfig(
            provider=(provider or env("LLM_PROVIDER") or llm["provider"]).strip().lower(),
            github_endpoint=env("GITHUB_MODELS_ENDPOINT") or llm["github_endpoint"],
            ollama_endpoint=env("OLLAMA_ENDPOINT") or llm["ollama_endpoint"],
            vision_model=env("VISION_MODEL") or llm["vision_model"],
            text_model=env("TEXT_MODEL") or llm["text_model"],
            ollama_vision_model=env("OLLAMA_VISION_MODEL") or llm["ollama_vision_model"],
            ollama_text_model=env("OLLAMA_TEXT_MODEL") or llm["ollama_text_model"],
            temperature=float(llm["temperature"]),
            max_retries=int(llm["max_retries"]),
            min_seconds_between_calls=float(llm["min_seconds_between_calls"]),
            request_timeout=float(llm["request_timeout"]),
            cache_responses=bool(llm["cache_responses"]),
        ),
        knowledge=KnowledgeConfig(advisory_review=bool(kn["advisory_review"]), top_k=int(kn["top_k"])),
        ingestion=IngestionConfig(
            max_pages=int(ing["max_pages"]),
            render_dpi=int(ing["render_dpi"]),
            ocr_enabled=bool(ing["ocr_enabled"]),
            ocr_languages=str(ing["ocr_languages"]),
        ),
        paths=Paths(
            root=root,
            master_dir=path("master_dir"),
            contracts_raw_dir=path("contracts_raw_dir"),
            rules_draft_dir=path("rules_draft_dir"),
            rules_approved_dir=path("rules_approved_dir"),
            policies_dir=path("policies_dir"),
            synthetic_dir=path("synthetic_dir"),
            runtime_dir=(runtime_dir or path("runtime_dir")).resolve(),
            reports_dir=(reports_dir or path("reports_dir")).resolve(),
            prompts_dir=path("prompts_dir"),
            users_file=path("users_file"),
        ),
    )
