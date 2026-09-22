"""Index contracts & policies into clause-level chunks with page references.

Source format (Markdown):
    ---
    vendor_id: V-NCS
    contract_id: NCS-2026
    title: ...
    ---
    <!-- page: 4 -->
    ## §2.1 Payment Terms
    clause text...
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

HEADING = re.compile(r"^##\s+(§[\d.]+|Annex\s+\w+)\s*[—:\-]?\s*(.*)$")
PAGE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")


@dataclass(frozen=True)
class Chunk:
    doc_id: str          # contract/policy id
    vendor_id: str | None
    clause: str
    title: str
    page: int | None
    text: str
    source_file: str
    doc_title: str = ""

    @property
    def citation(self) -> str:
        return f"[{self.doc_id} {self.clause}" + (f", p.{self.page}]" if self.page else "]")


def parse_document(path: Path) -> list[Chunk]:
    raw = path.read_text("utf-8")
    meta: dict = {}
    if raw.startswith("---"):
        _, fm, raw = raw.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    doc_id = meta.get("contract_id") or meta.get("policy_id") or path.stem
    vendor_id = meta.get("vendor_id")
    doc_title = str(meta.get("title") or "")

    chunks: list[Chunk] = []
    page: int | None = None
    clause, title, buf, clause_page = None, "", [], None

    def flush() -> None:
        if clause and "".join(buf).strip():
            chunks.append(Chunk(doc_id, vendor_id, clause, title, clause_page,
                                " ".join(" ".join(buf).split()), path.name, doc_title))

    for line in raw.splitlines():
        if m := PAGE.search(line):
            page = int(m.group(1))
            continue
        if m := HEADING.match(line.strip()):
            flush()
            clause, title, buf, clause_page = m.group(1), m.group(2).strip(), [], page
            continue
        if clause:
            buf.append(line)
    flush()
    return chunks


def build_index(source_dirs: list[Path], index_file: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for d in source_dirs:
        for path in sorted(Path(d).glob("*.md")):
            chunks.extend(parse_document(path))
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=1), "utf-8")
    return chunks


def load_index(index_file: Path) -> list[Chunk]:
    return [Chunk(**c) for c in json.loads(index_file.read_text("utf-8"))]
