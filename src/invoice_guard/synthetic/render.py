"""Render synthetic documents: digital PDF (reportlab) and degraded 'phone photo' (Pillow)."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _fmt(v: str) -> str:
    return f"{float(v):,.2f}"


def document_lines(doc: dict) -> list[str]:
    """Plain-text layout shared by the photo renderer."""
    inv = doc["invoice"]
    out = [doc["title"], "", doc["vendor_name"], doc["vendor_address"], f"VAT No: {inv['vendor_tax_id']}", ""]
    out += [f"{doc['number_label']}: {inv['invoice_number']}", f"Date: {inv['invoice_date']}"]
    if inv.get("due_date"):
        out.append(f"Due date: {inv['due_date']}")
    if inv.get("po_number"):
        out.append(f"PO: {inv['po_number']}")
    out += ["", f"Bill to: {doc['buyer_name']}", "", "SKU | Description | Qty | Unit | Amount"]
    for li in inv["line_items"]:
        out.append(f"{li['sku']} | {li['description']} | {li['quantity']} | {_fmt(li['unit_price'])} | {_fmt(li['line_total'])}")
    out += ["", f"Subtotal: {_fmt(inv['subtotal'])}"]
    if float(inv["shipping_fee"]):
        out.append(f"Shipping: {_fmt(inv['shipping_fee'])}")
    out += [f"VAT 15%: {_fmt(inv['tax_amount'])}", f"TOTAL ({inv['currency']}): {_fmt(inv['total'])}"]
    if inv.get("iban"):
        out += ["", f"Pay to IBAN: {inv['iban']}"]
    if inv.get("notes"):
        out += ["", f"Notes: {inv['notes']}"]
    return out


def render_pdf(path: Path, doc: dict) -> None:
    inv = doc["invoice"]
    c = canvas.Canvas(str(path), pagesize=A4, invariant=1)  # invariant -> reproducible bytes
    w, h = A4
    x0, y = 18 * mm, h - 22 * mm
    c.setFillColor(colors.HexColor("#1d2939"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x0, y, doc["title"])
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(w - x0, y, doc["vendor_name"])
    c.setFont("Helvetica", 9)
    c.drawRightString(w - x0, y - 13, doc["vendor_address"])
    c.drawRightString(w - x0, y - 25, f"VAT No: {inv['vendor_tax_id']}")

    y -= 50
    meta = [(doc["number_label"], inv["invoice_number"]), ("Date", inv["invoice_date"])]
    if inv.get("due_date"):
        meta.append(("Due date", inv["due_date"]))
    if inv.get("po_number"):
        meta.append(("Purchase order", inv["po_number"]))
    for label, value in meta:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x0, y, f"{label}:")
        c.setFont("Helvetica", 9)
        c.drawString(x0 + 32 * mm, y, str(value))
        y -= 13
    c.setFont("Helvetica-Bold", 9)
    c.drawString(w / 2, y + 13 * len(meta) - 13, "Bill to:")
    c.setFont("Helvetica", 9)
    c.drawString(w / 2, y + 13 * len(meta) - 26, doc["buyer_name"])
    c.drawString(w / 2, y + 13 * len(meta) - 39, doc["buyer_address"])

    y -= 14
    cols = [x0, x0 + 30 * mm, x0 + 112 * mm, x0 + 132 * mm, w - x0]
    c.setFillColor(colors.HexColor("#f2f4f7"))
    c.rect(x0, y - 4, w - 2 * x0, 16, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#1d2939"))
    c.setFont("Helvetica-Bold", 9)
    for text, x, right in [("SKU", cols[0] + 2, False), ("Description", cols[1], False),
                           ("Qty", cols[3] - 4, True), ("Unit price", cols[3] + 22 * mm, True),
                           ("Amount", cols[4] - 2, True)]:
        (c.drawRightString if right else c.drawString)(x, y, text)
    c.setFont("Helvetica", 9)
    for li in inv["line_items"]:
        y -= 16
        c.drawString(cols[0] + 2, y, li["sku"])
        c.drawString(cols[1], y, li["description"][:48])
        c.drawRightString(cols[3] - 4, y, str(li["quantity"]))
        c.drawRightString(cols[3] + 22 * mm, y, _fmt(li["unit_price"]))
        c.drawRightString(cols[4] - 2, y, _fmt(li["line_total"]))
    y -= 10
    c.line(x0, y, w - x0, y)

    totals = [("Subtotal", inv["subtotal"])]
    if float(inv["shipping_fee"]):
        totals.append(("Shipping", inv["shipping_fee"]))
    totals += [("VAT 15%", inv["tax_amount"]), (f"TOTAL ({inv['currency']})", inv["total"])]
    for label, value in totals:
        y -= 15
        bold = label.startswith("TOTAL")
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10 if bold else 9)
        c.drawRightString(cols[3] + 22 * mm, y, label)
        c.drawRightString(cols[4] - 2, y, _fmt(value))

    y -= 34
    c.setFont("Helvetica", 9)
    if inv.get("iban"):
        c.drawString(x0, y, f"Please pay by bank transfer to IBAN: {inv['iban']}")
        y -= 13
    for extra in doc.get("footer", []):
        c.drawString(x0, y, extra)
        y -= 13
    if inv.get("notes"):
        c.setFont("Helvetica-Oblique", 8)
        c.drawString(x0, y - 6, f"Notes: {inv['notes']}"[:140])
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#667085"))
    c.drawString(x0, 12 * mm, "SYNTHETIC TEST DOCUMENT - generated for Invoice Guard. Not a real invoice.")
    c.showPage()
    c.save()


def render_photo(path: Path, doc: dict, seed: int) -> None:
    rng = random.Random(seed)
    img = Image.new("RGB", (1240, 1754), (250, 249, 245))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=26)
        big = ImageFont.load_default(size=44)
    except TypeError:  # Pillow < 10.1
        font = big = ImageFont.load_default()
    y = 90
    for i, line in enumerate(document_lines(doc)):
        draw.text((90, y), line, fill=(30, 30, 35), font=big if i == 0 else font)
        y += 60 if i == 0 else 36
    draw.text((90, 1690), "SYNTHETIC TEST DOCUMENT", fill=(120, 120, 120), font=font)
    img = img.rotate(rng.uniform(-2.5, 2.5), expand=True, fillcolor=(60, 60, 60))
    img = img.filter(ImageFilter.GaussianBlur(0.9))
    small = (img.size[0] // 4, img.size[1] // 4)
    noise = Image.frombytes("L", small, rng.randbytes(small[0] * small[1]))
    noise = noise.resize(img.size).convert("RGB")  # seeded -> reproducible
    img = Image.blend(img, noise, 0.08)
    img.save(path, format="JPEG", quality=62)
