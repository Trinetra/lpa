"""Invoice PDF generation. Pure functions — no database or network."""

import io
import os
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Noto Sans/Serif are embedded because ReportLab's built-in Helvetica/Times
# don't include the ₹ glyph (renders as a missing-glyph box otherwise).
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "fonts")
_FONT_REGULAR = "NotoSans"
_FONT_BOLD = "NotoSans-Bold"
_FONT_ITALIC = "NotoSans-Italic"
_FONT_SERIF_BOLD = "NotoSerif-Bold"
_fonts_registered = False


def _ensure_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    pdfmetrics.registerFont(TTFont(_FONT_REGULAR, os.path.join(_FONTS_DIR, "NotoSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_BOLD, os.path.join(_FONTS_DIR, "NotoSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_ITALIC, os.path.join(_FONTS_DIR, "NotoSans-Italic.ttf")))
    pdfmetrics.registerFont(TTFont(_FONT_SERIF_BOLD, os.path.join(_FONTS_DIR, "NotoSerif-Bold.ttf")))
    _fonts_registered = True


# Palette matches Lakshmi's own outreach letterhead — deep maroon + warm
# gold on a cream ground — rather than the app's generic terracotta theme.
# This is *her* document, meant to look like it came from her, not the app.
_MAROON = colors.HexColor("#7A1F2B")
_GOLD = colors.HexColor("#C98A3A")
_INK = colors.HexColor("#2B2B2B")
_LABEL = colors.HexColor("#8A6D3B")
_RULE = colors.HexColor("#E4D9C8")
_ROW_TINT = colors.HexColor("#FBF5EC")
_DUE = colors.HexColor("#7A1F2B")
_PAID = colors.HexColor("#5C7A5E")

_PAGE_W = 174 * mm  # A4 width minus 18mm margins each side
_RUPEE = "₹"


def _styles():
    _ensure_fonts()
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow", parent=base["Normal"], fontName=_FONT_BOLD,
            fontSize=9, textColor=_MAROON, leading=11, alignment=1,
        ),
        "studio": ParagraphStyle(
            "studio", parent=base["Title"], fontName=_FONT_SERIF_BOLD,
            fontSize=15, leading=18, textColor=_MAROON, spaceAfter=0, alignment=1,
        ),
        "tagline": ParagraphStyle(
            "tagline", parent=base["Normal"], fontName=_FONT_REGULAR,
            fontSize=9, textColor=_LABEL, leading=12, alignment=1,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontName=_FONT_REGULAR,
            fontSize=8.5, textColor=_LABEL, leading=11,
        ),
        "sectionHead": ParagraphStyle(
            "sectionHead", parent=base["Normal"], fontName=_FONT_BOLD,
            fontSize=9.5, textColor=_INK, leading=12,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName=_FONT_ITALIC,
            fontSize=8.5, textColor=_LABEL, leading=11, alignment=1,
        ),
        "footerName": ParagraphStyle(
            "footerName", parent=base["Normal"], fontName=_FONT_SERIF_BOLD,
            fontSize=11, textColor=_MAROON, leading=14, alignment=1,
        ),
        "footerLinks": ParagraphStyle(
            "footerLinks", parent=base["Normal"], fontName=_FONT_REGULAR,
            fontSize=8.5, textColor=_LABEL, leading=11, alignment=1,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontName=_FONT_REGULAR,
            fontSize=9, textColor=_INK, leading=12, alignment=1,
        ),
        "cellHeader": ParagraphStyle(
            "cellHeader", parent=base["Normal"], fontName=_FONT_BOLD,
            fontSize=9, textColor=colors.white, leading=12, alignment=1,
        ),
    }


def _fmt_date(iso_date: Optional[str]) -> str:
    """dd MMM yyyy — reads naturally, matches every other date on the page.
    Accepts a plain YYYY-MM-DD or an ISO datetime string; only the date
    portion (first 10 chars) is ever needed here."""
    if not iso_date:
        return ""
    try:
        return datetime.strptime(iso_date[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return iso_date


def _fmt_hours(hours) -> str:
    """Whole hours as-is; a half hour as a raised 1/2 rather than '1.5'.
    Returns markup meant for a Paragraph (not a plain Table cell string)."""
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return str(hours)
    whole = int(h)
    frac = h - whole
    sup = '<super rise="3" size="7">1/2</super>'
    if abs(frac - 0.5) < 1e-6:
        return f"{whole} {sup}" if whole else sup
    if frac == 0:
        return str(whole)
    return f"{h:g}"


def _fmt_money(n) -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        v = 0.0
    if v == int(v):
        return f"{_RUPEE}{int(v):,}"
    return f"{_RUPEE}{v:,.2f}"


def _letterhead(styles, teacher_name: str, studio_name: Optional[str] = None,
                logo_bytes: Optional[bytes] = None, doc_label: str = "Invoice"):
    """Centered logo (large), studio name in a smaller elegant serif caption
    beneath it — mirrors the centered symmetry of the outreach letterhead
    rather than a left-logo/right-text business-card layout."""
    els = [Paragraph(doc_label.upper(), styles["eyebrow"]), Spacer(1, 3 * mm)]

    if logo_bytes:
        try:
            img = RLImage(io.BytesIO(logo_bytes))
            ratio = (img.imageWidth or 1) / (img.imageHeight or 1)
            img.drawHeight = 30 * mm
            img.drawWidth = 30 * mm * ratio
            img.hAlign = "CENTER"
            els.append(img)
            els.append(Spacer(1, 3 * mm))
        except Exception:
            pass

    if studio_name:
        els.append(Paragraph(studio_name, styles["studio"]))
        els.append(Spacer(1, 1 * mm))
        els.append(Paragraph(f"{teacher_name} · Dance", styles["tagline"]))
    else:
        els.append(Paragraph(teacher_name, styles["studio"]))
        els.append(Spacer(1, 1 * mm))
        els.append(Paragraph("Dance Classes", styles["tagline"]))

    els.append(Spacer(1, 5 * mm))
    els.append(Table([[""]], colWidths=[_PAGE_W], rowHeights=[0.8],
                      style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, _GOLD)])))
    els.append(Spacer(1, 7 * mm))
    return els


def _meta_card(styles, rows: list) -> Table:
    cells = []
    for label, value in rows:
        cells.append([
            Paragraph(label.upper(), ParagraphStyle(
                "mc-label", parent=styles["label"], fontSize=8, leading=10,
            )),
            Paragraph(value, ParagraphStyle(
                "mc-value", parent=styles["label"], fontName=_FONT_BOLD,
                fontSize=10, textColor=_INK, leading=13,
            )),
        ])
    tbl = Table(cells, colWidths=[32 * mm, _PAGE_W - 32 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBF5EC")),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (0, -1), 6 * mm),
        ("LEFTPADDING", (1, 0), (1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _line_items_table(styles, header_labels: list, data_rows: list, col_widths: list) -> Table:
    """All data columns centered under their headers. Every cell is a real
    Paragraph (not a bare string) so inline markup like <super> actually
    renders instead of showing as literal tag text."""
    header = [Paragraph(h, styles["cellHeader"]) for h in header_labels]
    rows = [header]
    for row in data_rows:
        rows.append([Paragraph(str(v), styles["cell"]) for v in row])

    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _MAROON),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, _RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
    ]
    for i in range(1, len(rows)):
        if (i - 1) % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), _ROW_TINT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _summary_card(styles, rows: list, emphasis_index: int, emphasis_color) -> Table:
    label_style = ParagraphStyle("sc-label", parent=styles["label"], fontSize=10, leading=13)
    value_style = ParagraphStyle("sc-value", parent=styles["label"], fontSize=10.5,
                                  textColor=_INK, leading=13, alignment=2)
    cells = [[Paragraph(label, label_style), Paragraph(value, value_style)] for label, value in rows]

    emph_label, emph_value = rows[emphasis_index]
    emph_label_style = ParagraphStyle("sc-elabel", parent=styles["label"], fontName=_FONT_BOLD,
                                       fontSize=11, textColor=colors.white, leading=14)
    emph_value_style = ParagraphStyle("sc-evalue", parent=styles["label"], fontName=_FONT_BOLD,
                                       fontSize=13, textColor=colors.white, leading=16, alignment=2)
    cells[emphasis_index] = [Paragraph(emph_label, emph_label_style), Paragraph(emph_value, emph_value_style)]

    tbl = Table(cells, colWidths=[65 * mm, 45 * mm], hAlign="RIGHT")
    style = [
        ("TOPPADDING", (0, 0), (-1, -2), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -2), 2.5),
        ("TOPPADDING", (0, emphasis_index), (-1, emphasis_index), 5),
        ("BOTTOMPADDING", (0, emphasis_index), (-1, emphasis_index), 5),
        ("BACKGROUND", (0, emphasis_index), (-1, emphasis_index), emphasis_color),
        ("LEFTPADDING", (0, emphasis_index), (0, emphasis_index), 4 * mm),
        ("RIGHTPADDING", (0, emphasis_index), (-1, emphasis_index), 4 * mm),
        ("LINEABOVE", (0, emphasis_index), (-1, emphasis_index), 0.4, _RULE),
    ]
    tbl.setStyle(TableStyle(style))
    return tbl


def _footer(styles, teacher_name: str, studio_contact: Optional[dict]) -> list:
    """Centered teacher-name signature with a rule and socials — mirrors the
    outreach letterhead's own centered sign-off block."""
    els = [
        Spacer(1, 8 * mm),
        Table([[""]], colWidths=[70 * mm], hAlign="CENTER", rowHeights=[0.6],
              style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.6, _RULE)])),
        Spacer(1, 4 * mm),
        Paragraph(teacher_name, styles["footerName"]),
    ]
    social_line = _social_links_line(studio_contact)
    if social_line:
        els.append(Spacer(1, 2 * mm))
        els.append(Paragraph(social_line, styles["footerLinks"]))
    return els


def _social_links_line(studio_contact: Optional[dict]) -> Optional[str]:
    if not studio_contact:
        return None
    bits = []
    if studio_contact.get("social_youtube"):
        bits.append(f'<link href="{studio_contact["social_youtube"]}"><u>YouTube</u></link>')
    if studio_contact.get("social_instagram"):
        bits.append(f'<link href="{studio_contact["social_instagram"]}"><u>Instagram</u></link>')
    if studio_contact.get("social_facebook"):
        bits.append(f'<link href="{studio_contact["social_facebook"]}"><u>Facebook</u></link>')
    return " &nbsp;·&nbsp; ".join(bits) if bits else None


def generate_invoice_pdf(teacher_name: str, student: dict, classes: list,
                         payments: list, summary: dict, start: Optional[str],
                         end: Optional[str], studio_name: Optional[str] = None,
                         logo_bytes: Optional[bytes] = None,
                         studio_contact: Optional[dict] = None,
                         invoice_number: Optional[str] = None,
                         created_at: Optional[str] = None) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    story.extend(_letterhead(styles, teacher_name, studio_name, logo_bytes, doc_label="Invoice"))

    contact_line = " · ".join(filter(None, [student.get("email"), student.get("phone")]))
    story.append(_meta_card(styles, [
        ("Invoice #", invoice_number or "—"),
        ("Date", _fmt_date(created_at)),
        ("Billed to", student.get("name", "")),
        ("Contact", contact_line or "—"),
        ("Period", f"{_fmt_date(start) or 'All time'} – {_fmt_date(end) or 'Today'}"),
    ]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("CLASSES", styles["sectionHead"]))
    story.append(Spacer(1, 2.5 * mm))
    class_rows = [[
        _fmt_date(c.get("class_date")), _fmt_hours(c.get("hours", 0)),
        _fmt_money(c.get("amount", 0)), c.get("notes") or "",
    ] for c in classes]
    story.append(_line_items_table(
        styles, ["Date", "Hours", "Amount", "Notes"],
        class_rows, [32 * mm, 24 * mm, 30 * mm, _PAGE_W - 86 * mm],
    ))
    story.append(Spacer(1, 7 * mm))

    if payments:
        story.append(Paragraph("PAYMENTS RECEIVED", styles["sectionHead"]))
        story.append(Spacer(1, 2.5 * mm))
        pay_rows = [[
            _fmt_date(p.get("paid_on")), p.get("method") or "—", _fmt_money(p.get("amount", 0)), p.get("notes") or "",
        ] for p in payments]
        story.append(_line_items_table(
            styles, ["Date", "Method", "Amount", "Notes"],
            pay_rows, [32 * mm, 34 * mm, 30 * mm, _PAGE_W - 96 * mm],
        ))
        story.append(Spacer(1, 7 * mm))

    total_billed = summary.get("total_billed", 0)
    total_paid = summary.get("total_paid", 0)
    balance_due = summary.get("balance_due", 0)
    has_credit = balance_due < 0

    summary_rows = [("Total billed", _fmt_money(total_billed)), ("Total paid", _fmt_money(total_paid))]
    if has_credit:
        summary_rows.append(("Credit balance", _fmt_money(abs(balance_due))))
        summary_rows.append(("Final Amount Due", _fmt_money(0)))
        emphasis_color = _PAID
    else:
        summary_rows.append(("Final Amount Due", _fmt_money(balance_due)))
        emphasis_color = _DUE if balance_due > 0 else _PAID

    story.append(_summary_card(styles, summary_rows, emphasis_index=len(summary_rows) - 1,
                                emphasis_color=emphasis_color))
    story.append(Spacer(1, 7 * mm))

    if studio_contact and balance_due > 0:
        contact_bits = []
        if studio_contact.get("contact_upi"):
            contact_bits.append(f"UPI: <b>{studio_contact['contact_upi']}</b>")
        if studio_contact.get("contact_phone"):
            contact_bits.append(f"Phone: {studio_contact['contact_phone']}")
        if studio_contact.get("contact_email"):
            contact_bits.append(f"Email: {studio_contact['contact_email']}")
        if contact_bits:
            story.append(Paragraph("<b>Pay to:</b> " + " · ".join(contact_bits), styles["label"]))
            story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(
        "Thank you for learning with us. Please remit any balance at your earliest convenience.",
        ParagraphStyle("thanks", parent=styles["footer"], alignment=0)))

    story.extend(_footer(styles, teacher_name, studio_contact))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def generate_tour_expense_pdf(tour: dict, expenses: list) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    story.append(Paragraph("TOUR EXPENSES", ParagraphStyle(
        "te-eyebrow", parent=styles["eyebrow"], alignment=0)))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(tour.get("name", ""), ParagraphStyle(
        "te-name", parent=styles["studio"], alignment=0)))
    period = f"{_fmt_date(tour.get('start_date'))} – {_fmt_date(tour.get('end_date'))}"
    story.append(Paragraph(period, ParagraphStyle(
        "te-period", parent=styles["tagline"], alignment=0)))
    story.append(Spacer(1, 3 * mm))
    story.append(Table([[""]], colWidths=[_PAGE_W], rowHeights=[0.8],
                        style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.8, _GOLD)])))
    story.append(Spacer(1, 7 * mm))

    total = sum(float(e.get("amount", 0)) for e in expenses)
    rows = [[
        _fmt_date(e.get("expense_date")), e.get("category", ""), _fmt_money(e.get("amount", 0)),
        e.get("notes") or "",
    ] for e in expenses]
    story.append(_line_items_table(
        styles, ["Date", "Category", "Amount", "Notes"],
        rows, [30 * mm, 40 * mm, 30 * mm, _PAGE_W - 100 * mm],
    ))
    story.append(Spacer(1, 7 * mm))
    story.append(_summary_card(
        styles, [("Total", _fmt_money(total))], emphasis_index=0, emphasis_color=_MAROON,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
