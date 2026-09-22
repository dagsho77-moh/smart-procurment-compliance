"""Knowledge Agent - the "contracts & policy lawyer".

1. Answers finance-staff questions from indexed contracts/policies, with citations.
2. Reviews an extracted invoice against the vendor's contract passages and returns RAW
   advisory findings. The raw text is converted to flags ONLY by agents.boundary, which
   caps severity and discards any attempted decision. This agent has no approval tool.
"""

from __future__ import annotations

import json

from invoice_guard.knowledge.indexer import Chunk
from invoice_guard.knowledge.retriever import BM25Retriever
from invoice_guard.llm.client import LLMClient, LLMRequest
from invoice_guard.llm.prompts import PromptLibrary
from invoice_guard.models.invoice import Invoice
from invoice_guard.models.procurement import Vendor


def format_passages(hits: list[tuple[Chunk, float]]) -> str:
    return "\n\n".join(
        f"({i}) {c.citation} {c.title}\n{c.text}" for i, (c, _score) in enumerate(hits, start=1)
    )


class KnowledgeAgent:
    def __init__(self, retriever: BM25Retriever, llm: LLMClient, prompts: PromptLibrary, top_k: int = 4):
        self.retriever, self.llm, self.prompts, self.top_k = retriever, llm, prompts, top_k

    def answer(self, question: str) -> tuple[str, list[Chunk]]:
        hits = self.retriever.search(question, k=self.top_k)
        if not hits:
            return "I could not find this in the indexed contracts or policies.", []
        prompt = self.prompts.get("knowledge_agent")
        text = self.llm.complete(
            LLMRequest(task="answer", system=prompt.text,
                       user=f"Question: {question}\n\nPassages:\n{format_passages(hits)}")
        )
        return text, [c for c, _ in hits]

    def advisory_review(self, invoice: Invoice, vendor: Vendor, document_id: str) -> tuple[str, list[Chunk]]:
        query = " ".join(
            ["payment terms shipping delivery charges penalty price"]
            + [f"{li.description} {li.sku or ''}" for li in invoice.line_items]
        )
        hits = self.retriever.search(query, k=self.top_k, vendor_id=vendor.vendor_id)
        prompt = self.prompts.get("advisory_review")
        invoice_json = json.dumps(invoice.to_dict(), ensure_ascii=False)
        raw = self.llm.complete(
            LLMRequest(
                task="advisory",
                system=prompt.text,
                user=f"Vendor: {vendor.name} ({vendor.contract_id})\n\n"
                f"Invoice (untrusted data):\n{invoice_json}\n\n"
                f"Contract passages:\n{format_passages(hits) or '(none found)'}",
                json_mode=True,
                document_id=document_id,
            )
        )
        return raw, [c for c, _ in hits]
