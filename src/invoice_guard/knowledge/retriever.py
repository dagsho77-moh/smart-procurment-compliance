"""Dependency-free BM25 retriever. Unicode tokenisation works for Arabic and English."""

from __future__ import annotations

import math
import re
from collections import Counter

from invoice_guard.knowledge.indexer import Chunk

TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text) if len(t) > 1]


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        # Document title is included so "the computer supply contract" finds that contract's clauses.
        self._docs = [Counter(tokenize(f"{c.doc_title} {c.clause} {c.title} {c.text}")) for c in chunks]
        self._lens = [sum(d.values()) for d in self._docs]
        self._avg = (sum(self._lens) / len(self._lens)) if self._lens else 0.0
        df: Counter = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 4, vendor_id: str | None = None,
               include_policies: bool = True) -> list[tuple[Chunk, float]]:
        terms = tokenize(query)
        scored = []
        for chunk, doc, length in zip(self.chunks, self._docs, self._lens, strict=True):
            if vendor_id and chunk.vendor_id not in (vendor_id, None):
                continue
            if not include_policies and chunk.vendor_id is None:
                continue
            score = 0.0
            for t in terms:
                if t in doc:
                    tf = doc[t]
                    score += self._idf.get(t, 0.0) * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * length / (self._avg or 1))
                    )
            if score > 0:
                scored.append((chunk, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
