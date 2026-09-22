"""Load invoices (digital PDF, scan, phone photo) into text + page images."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from invoice_guard.config import IngestionConfig

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
MAX_IMAGE_SIDE = 1600


@dataclass(frozen=True)
class LoadedDocument:
    path: Path
    sha256: str
    kind: str                 # "pdf" | "image"
    text: str                 # embedded or OCR text ('' if none)
    page_images: tuple[bytes, ...]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _png_bytes(image) -> bytes:
    image = image.convert("RGB")
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def load_document(path: Path, cfg: IngestionConfig, *, render_images: bool = True) -> LoadedDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type: {path.name}")
    digest = file_sha256(path)

    if suffix == ".pdf":
        import pdfplumber

        texts: list[str] = []
        images: list[bytes] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages[: cfg.max_pages]:
                texts.append(page.extract_text() or "")
                if render_images:
                    images.append(_png_bytes(page.to_image(resolution=cfg.render_dpi).original))
        text = "\n".join(texts).strip()
        if not text and cfg.ocr_enabled and images:
            from invoice_guard.ingestion.ocr import ocr_images

            text = ocr_images(images, cfg.ocr_languages)
        return LoadedDocument(path, digest, "pdf", text, tuple(images))

    from PIL import Image

    with Image.open(path) as img:
        png = _png_bytes(img)
    text = ""
    if cfg.ocr_enabled:
        from invoice_guard.ingestion.ocr import ocr_images

        text = ocr_images([png], cfg.ocr_languages)
    return LoadedDocument(path, digest, "image", text, (png,) if render_images else ())
