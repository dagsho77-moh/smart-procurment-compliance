"""End-to-end: full pipeline on synthetic invoices with the deterministic mock LLM."""

import tempfile
from pathlib import Path

from invoice_guard.evaluation import evaluate
from invoice_guard.knowledge.indexer import build_index
from invoice_guard.knowledge.retriever import BM25Retriever
from invoice_guard.llm.client import MockLLMClient
from invoice_guard.synthetic.generator import generate
from tests.helpers import settings, with_paths


def test_committed_synthetic_set_scores_perfectly():
    s = settings(tempfile.mkdtemp())
    result = evaluate(s, quiet=True)
    assert result["status_accuracy"] == 1.0
    assert result["check_f1"] == 1.0
    assert Path(result["report"]).exists()


def test_freshly_generated_set_with_another_seed():
    tmp = Path(tempfile.mkdtemp())
    s = with_paths(settings(tmp), synthetic_dir=tmp / "synthetic", master_dir=tmp / "master")
    manifest = generate(s.paths.synthetic_dir, s.paths.master_dir, clean_count=6, seed=7)
    assert len(manifest["cases"]) == 24
    llm = MockLLMClient([s.paths.synthetic_dir / "_truth"])
    result = evaluate(s, s.paths.synthetic_dir, llm=llm, quiet=True)
    assert result["score"] == 1.0, result["per_check"]


def test_knowledge_retrieval_finds_contract_clause_with_page():
    s = settings(tempfile.mkdtemp())
    chunks = build_index([s.paths.contracts_raw_dir, s.paths.policies_dir], s.paths.index_file)
    hits = BM25Retriever(chunks).search("payment terms days", vendor_id="V-NCS", k=1)
    assert hits and hits[0][0].citation == "[NCS-2026 §2.1, p.4]"
    policy = BM25Retriever(chunks).search("maintenance invoices exceeding 10,000 prior authorisation", k=1)
    assert policy[0][0].doc_id == "PROC-POLICY-2026"
