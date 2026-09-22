"""Optional Tesseract OCR fallback (free). Requires `pip install pytesseract` and the
Tesseract binary with Arabic data ('ara'). The vision LLM reads images directly, so OCR
only adds a text hint for scans; the pipeline works without it."""

from __future__ import annotations

import io


def ocr_images(images: list[bytes], languages: str = "ara+eng") -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    parts = []
    for data in images:
        try:
            parts.append(pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang=languages))
        except Exception:  # noqa: BLE001 - OCR is best-effort
            continue
    return "\n".join(parts).strip()
