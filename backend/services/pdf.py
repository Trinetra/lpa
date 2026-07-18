"""Invoice PDF generation. Pure functions — no database or network."""

import io
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_PDF_ACCENT = colors.HexColor("#D48464")
_PDF_MUTED = colors.HexColor("#666666")
_PDF_HEADER_BG = colors.HexColor("#F5E6D3")
_PDF_TEXT_DARK = colors.HexColor("#1A1816")
_PDF_GRID = colors.HexColor("#DDDDDD")
_PDF_DUE = colors.HexColor("#B85C5C")
_PDF_RULE = colors.HexColor("#888888")


def _pdf_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=22, textColor=_PDF_ACCENT),
        "label": ParagraphStyle("l", parent=base["Normal"], fontSize=9, textColor=_PDF_MUTED),
        "body": base["Normal"],
    }


def _pdf_header(styles, teacher_name: str, studio_name: Optional[str] = None,
                logo_bytes: Optional[bytes] = None):
    els = []
    if logo_bytes:
        try:
            img = RLImage(io.BytesIO(logo_bytes))
            ratio = (img.imageWidth or 1) / (img.imageHeight or 1)
            img.drawHeight = 22 * mm
            img.drawWidth = 22 * mm * ratio
            img.hAlign = "LEFT"
            els.append(img)
            els.append(Spacer(1, 3 * mm))
        except Exception:
            pass
    if studio_name:
        studio_style = ParagraphStyle("s", parent=styles["title"], fontSize=16, textColor=_PDF_TEXT_DARK)
        els.append(Paragraph(studio_name, studio_style))
    els.append(Paragraph("Invoice", styles["title"]))
    els.append(Paragraph(f"From <b>{teacher_name}</b> — Dance Classes", styles["label"]))
    els.append(Spacer(1, 8 * mm))
    return els


def _pdf_meta_table(student: dict, start: Optional[str], end: Optional[str]):
    now = datetime.now(timezone.utc)
    rows = [
        ["Invoice #", f"INV-{now.strftime('%Y%m%d%H%M%S')}"],
        ["Date", now.strftime("%d %b %Y")],
        ["Billed to", student.get("name", "")],
        ["Contact", f"{student.get('email','') or ''} {student.get('phone','') or ''}"],
        ["Period", f"{start or 'All time'} to {end or 'Today'}"],
    ]
    t = Table(rows, colWidths=[35 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888888")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _pdf_classes_table(classes: list) -> Table:
    rows = [["Date", "Hours", "Rate (INR/hr)", "Amount (INR)", "Notes"]]
    for c in classes:
        rows.append([
            c.get("class_date", ""),
            f"{c.get('hours', 0)}",
            f"{c.get('rate', 0)}",
            f"{c.get('amount', 0)}",
            c.get("notes") or "",
        ])
    tbl = Table(rows, colWidths=[28 * mm, 18 * mm, 30 * mm, 30 * mm, 60 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PDF_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _PDF_TEXT_DARK),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, _PDF_GRID),
        ("ALIGN", (1, 1), (3, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    return tbl


def _pdf_payments_table(payments: list) -> Table:
    rows = [["Date", "Method", "Amount (INR)", "Notes"]]
    for p in payments:
        rows.append([
            p.get("paid_on", ""),
            p.get("method") or "-",
            f"{p.get('amount', 0)}",
            p.get("notes") or "",
        ])
    tbl = Table(rows, colWidths=[28 * mm, 32 * mm, 30 * mm, 76 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _PDF_HEADER_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, _PDF_GRID),
        ("ALIGN", (2, 1), (2, -1), "RIGHT"),
    ]))
    return tbl


def _pdf_summary_table(summary: dict) -> Table:
    rows = [
        ["Total billed", f"INR {summary.get('total_billed', 0)}"],
        ["Total paid", f"INR {summary.get('total_paid', 0)}"],
        ["Balance due", f"INR {summary.get('balance_due', 0)}"],
    ]
    tbl = Table(rows, colWidths=[60 * mm, 40 * mm], hAlign="RIGHT")
    tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 2), (-1, 2), _PDF_DUE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE", (0, 2), (-1, 2), 0.6, _PDF_RULE),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    return tbl


def generate_invoice_pdf(teacher_name: str, student: dict, classes: list,
                         payments: list, summary: dict, start: Optional[str],
                         end: Optional[str], studio_name: Optional[str] = None,
                         logo_bytes: Optional[bytes] = None,
                         studio_contact: Optional[dict] = None) -> bytes:
    styles = _pdf_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    story = []
    story.extend(_pdf_header(styles, teacher_name, studio_name, logo_bytes))
    story.append(_pdf_meta_table(student, start, end))
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("<b>Classes</b>", styles["body"]))
    story.append(Spacer(1, 3 * mm))
    story.append(_pdf_classes_table(classes))
    story.append(Spacer(1, 6 * mm))
    if payments:
        story.append(Paragraph("<b>Payments Received</b>", styles["body"]))
        story.append(Spacer(1, 3 * mm))
        story.append(_pdf_payments_table(payments))
        story.append(Spacer(1, 6 * mm))
    story.append(_pdf_summary_table(summary))
    story.append(Spacer(1, 6 * mm))
    if studio_contact and summary.get("balance_due", 0) > 0:
        contact_bits = []
        if studio_contact.get("contact_upi"):
            contact_bits.append(f"UPI: <b>{studio_contact['contact_upi']}</b>")
        if studio_contact.get("contact_phone"):
            contact_bits.append(f"Phone: {studio_contact['contact_phone']}")
        if studio_contact.get("contact_email"):
            contact_bits.append(f"Email: {studio_contact['contact_email']}")
        if contact_bits:
            story.append(Paragraph(
                "<b>Pay to:</b> " + " · ".join(contact_bits), styles["label"]))
            story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "<i>Thank you for learning with us. Please remit any balance at your earliest convenience.</i>",
        styles["label"]))
    doc.build(story)
    buf.seek(0)
    return buf.read()
