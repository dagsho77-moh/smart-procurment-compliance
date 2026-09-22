"""Versioned prompt files (config/prompts/<name>.v<N>.txt). The version is logged in traces."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


class PromptLibrary:
    def __init__(self, prompts_dir: Path):
        self._dir = prompts_dir

    def get(self, name: str) -> Prompt:
        candidates = sorted(
            self._dir.glob(f"{name}.v*.txt"),
            key=lambda p: int(re.search(r"\.v(\d+)\.txt$", p.name).group(1)),  # type: ignore[union-attr]
        )
        if not candidates:
            raise FileNotFoundError(f"No prompt file for {name!r} in {self._dir}")
        latest = candidates[-1]
        version = re.search(r"\.(v\d+)\.txt$", latest.name).group(1)  # type: ignore[union-attr]
        return Prompt(name=name, version=version, text=latest.read_text("utf-8").strip())
