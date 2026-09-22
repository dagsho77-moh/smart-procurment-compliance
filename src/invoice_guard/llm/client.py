"""LLM access for GitHub Models (free tier), Ollama (local) or a deterministic mock.

GitHub Models and Ollama both expose an OpenAI-compatible Chat Completions API,
so one client serves both. The mock replays synthetic ground truth so the whole
pipeline, the tests and CI run offline without spending any quota.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from invoice_guard.config import Settings


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMRequest:
    task: str                       # classify | extract | advisory | answer | draft_rules
    system: str
    user: str
    images: tuple[bytes, ...] = ()  # PNG/JPEG bytes
    json_mode: bool = False
    document_id: str | None = None  # file sha256 (lets the mock find ground truth)


class LLMClient(Protocol):
    provider: str
    needs_images: bool

    def model_for(self, request: LLMRequest) -> str: ...
    def complete(self, request: LLMRequest) -> str: ...


class OpenAICompatibleClient:
    """Client for GitHub Models / Ollama with throttling, retries and a disk cache."""

    needs_images = True

    def __init__(self, settings: Settings):
        cfg = settings.llm
        self.provider = cfg.provider
        self._cfg = cfg
        if cfg.provider == "github":
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            if not token:
                raise LLMError(
                    "GITHUB_TOKEN is not set. Add it to .env (fine-grained PAT with Models: read), "
                    "or run offline with LLM_PROVIDER=mock."
                )
            base_url, self._vision, self._text = cfg.github_endpoint, cfg.vision_model, cfg.text_model
        elif cfg.provider == "ollama":
            token = "ollama"  # ignored by Ollama but required by the SDK
            base_url = cfg.ollama_endpoint
            self._vision, self._text = cfg.ollama_vision_model, cfg.ollama_text_model
        else:
            raise LLMError(f"Unsupported provider for OpenAICompatibleClient: {cfg.provider}")

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError("The 'openai' package is required: pip install -r requirements.txt") from exc

        self._client = OpenAI(base_url=base_url, api_key=token, timeout=cfg.request_timeout)
        self._cache_dir = settings.paths.llm_cache_dir if cfg.cache_responses else None
        self._last_call = 0.0

    def model_for(self, request: LLMRequest) -> str:
        return self._vision if request.images else self._text

    # -- caching ---------------------------------------------------------------
    def _cache_key(self, request: LLMRequest, model: str) -> str:
        h = hashlib.sha256()
        for part in (self.provider, model, request.system, request.user, str(request.json_mode)):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        for img in request.images:
            h.update(hashlib.sha256(img).digest())
        return h.hexdigest()

    def _cache_get(self, key: str) -> str | None:
        if not self._cache_dir:
            return None
        path = self._cache_dir / f"{key}.json"
        return json.loads(path.read_text("utf-8"))["content"] if path.exists() else None

    def _cache_put(self, key: str, content: str) -> None:
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            (self._cache_dir / f"{key}.json").write_text(json.dumps({"content": content}), "utf-8")

    # -- request ---------------------------------------------------------------
    def _throttle(self) -> None:
        wait = self._cfg.min_seconds_between_calls - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def complete(self, request: LLMRequest) -> str:
        from openai import (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            RateLimitError,
        )

        model = self.model_for(request)
        key = self._cache_key(request, model)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        if request.images:
            content: object = [{"type": "text", "text": request.user}] + [
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64," + base64.b64encode(img).decode()},
                }
                for img in request.images
            ]
        else:
            content = request.user
        kwargs: dict = {
            "model": model,
            "temperature": self._cfg.temperature,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": content},
            ],
        }
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        delay = 5.0
        for attempt in range(1, self._cfg.max_retries + 1):
            self._throttle()
            try:
                response = self._client.chat.completions.create(**kwargs)
                text = response.choices[0].message.content or ""
                self._cache_put(key, text)
                return text
            except RateLimitError as exc:
                retry_after = _retry_after_seconds(exc) or delay
                if attempt == self._cfg.max_retries:
                    raise LLMError(
                        "Rate limit reached (GitHub Models free tier has per-minute and per-day "
                        "limits). Try later, lower the batch, or switch LLM_PROVIDER=ollama."
                    ) from exc
                time.sleep(min(retry_after, 120))
            except (APIConnectionError, APITimeoutError) as exc:
                if attempt == self._cfg.max_retries:
                    raise LLMError(f"LLM endpoint unreachable: {exc}") from exc
                time.sleep(delay)
            except APIStatusError as exc:
                if exc.status_code >= 500 and attempt < self._cfg.max_retries:
                    time.sleep(delay)
                else:
                    raise LLMError(f"LLM request failed ({exc.status_code}): {exc}") from exc
            delay = min(delay * 2, 60)
        raise LLMError("LLM request failed after retries")  # pragma: no cover


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


class MockLLMClient:
    """Deterministic offline LLM that replays synthetic ground truth.

    It still returns *raw text*, so outputs go through exactly the same parsing,
    validation and agent-boundary code as real model output.
    """

    provider = "mock"
    needs_images = False

    def __init__(self, truth_dirs: list[Path]):
        self._truth: dict[str, dict] = {}
        for d in truth_dirs:
            for path in sorted(Path(d).glob("*.json")):
                data = json.loads(path.read_text("utf-8"))
                self._truth.setdefault(data["file_sha256"], data)

    def model_for(self, request: LLMRequest) -> str:
        return "mock"

    def complete(self, request: LLMRequest) -> str:
        truth = self._truth.get(request.document_id or "")
        if request.task == "classify":
            if truth is None:
                return "Uncertain - no ground truth for this document"
            return "Invoice" if truth["doc_type"] == "invoice" else "Invalid"
        if request.task == "extract":
            if truth is None or truth.get("invoice") is None:
                return "not json"
            return json.dumps(truth["invoice"])
        if request.task == "advisory":
            if truth and truth.get("mock_advisory_response") is not None:
                return truth["mock_advisory_response"]
            return json.dumps({"findings": []})
        if request.task == "answer":
            return "[mock answer] Relevant passages:\n" + request.user
        if request.task == "draft_rules":
            return json.dumps({"rules": []})
        raise LLMError(f"MockLLMClient: unknown task {request.task!r}")


def create_llm_client(settings: Settings, truth_dirs: list[Path] | None = None) -> LLMClient:
    if settings.llm.provider == "mock":
        dirs = truth_dirs or [settings.paths.synthetic_dir / "_truth"]
        return MockLLMClient(dirs)
    return OpenAICompatibleClient(settings)
