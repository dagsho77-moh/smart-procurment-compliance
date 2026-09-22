"""Tool 2 - Extraction: document -> validated, structured Invoice (replaces Azure prebuilt-invoice)."""

from __future__ import annotations

import json
import re

from invoice_guard.ingestion.loader import LoadedDocument
from invoice_guard.llm.client import LLMClient, LLMRequest
from invoice_guard.llm.prompts import PromptLibrary
from invoice_guard.models.invoice import Invoice, InvoiceValidationError


def parse_json_object(raw: str) -> dict:
    """Parse a JSON object from model output, tolerating ```json fences."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.MULTILINE).strip()
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        cleaned = match.group(0) if match else cleaned
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def extract_invoice(
    doc: LoadedDocument, llm: LLMClient, prompts: PromptLibrary
) -> tuple[Invoice | None, list[str], str]:
    """Returns (invoice or None, validation errors, raw model output)."""
    prompt = prompts.get("extractor")
    user = "Extract the invoice fields."
    if doc.text:
        user += "\n\nEmbedded text layer (use it to read numbers precisely):\n" + doc.text[:8000]
    raw = llm.complete(
        LLMRequest(
            task="extract",
            system=prompt.text,
            user=user,
            images=doc.page_images,
            json_mode=True,
            document_id=doc.sha256,
        )
    )
    try:
        data = parse_json_object(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        return None, [f"extractor output is not valid JSON: {exc}"], raw
    try:
        return Invoice.from_dict(data), [], raw
    except InvoiceValidationError as exc:
        return None, exc.errors, raw
