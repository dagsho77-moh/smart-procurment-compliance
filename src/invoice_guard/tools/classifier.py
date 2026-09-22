"""Tool 1 - File check & classification: is this really an invoice?"""

from __future__ import annotations

import re
from enum import Enum

from invoice_guard.ingestion.loader import LoadedDocument
from invoice_guard.llm.client import LLMClient, LLMRequest
from invoice_guard.llm.prompts import PromptLibrary


class DocClass(str, Enum):
    INVOICE = "Invoice"
    INVALID = "Invalid"
    UNCERTAIN = "Uncertain"  # model did not answer with one of the two allowed words


def normalize_label(raw: str) -> DocClass:
    word = re.sub(r"[^a-z]", "", (raw or "").strip().lower())
    if word == "invoice":
        return DocClass.INVOICE
    if word == "invalid":
        return DocClass.INVALID
    return DocClass.UNCERTAIN


def classify_document(doc: LoadedDocument, llm: LLMClient, prompts: PromptLibrary) -> tuple[DocClass, str]:
    prompt = prompts.get("classifier")
    user = "Classify this document."
    if doc.text:
        user += "\n\nExtracted text (may be partial):\n" + doc.text[:4000]
    raw = llm.complete(
        LLMRequest(
            task="classify",
            system=prompt.text,
            user=user,
            images=doc.page_images[:1],
            document_id=doc.sha256,
        )
    )
    return normalize_label(raw), raw
