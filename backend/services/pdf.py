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

# Warm, terracotta-biased palette — matches the studio's own brand accent
# rather than a generic invoice grey/blue scheme.
_ACCENT = colors.HexColor("#C97B56")       # terracotta — the one accent color
_ACCENT_SOFT = colors.HexColor("#F3E4D8")  # tinted fill for the header band
_INK = colors.HexColor("#2A241F")          # warm near-black for body text
_LABEL = colors.HexColor("#96877A")        # warm grey for eyebrows/labels
_RULE = colors.HexColor("#E7DACB")         # warm hairline, not blue-grey
_ROW_TINT = colors.HexColor("#FAF6F1")     # zebra stripe, barely-there
_DUE = colors.HexColor("#B14B3F")          # balance-due red, warm-shifted
_PAID = colors.HexColor("#5C7A5E")         # settled/paid green, warm-shifted

_PAGE_W = 174 * mm  # A4 width minus 18mm margins each side


def _styles():
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9, textColor=_ACCENT, leading=11,
        ),
        "studio": ParagraphStyle(
            "studio", parent=base["Title"], fontName="Times-Bold",
            fontSize=21, leading=24, textColor=_INK, spaceAfter=0,
        ),
        "tagline": ParagraphStyle(
            "tagline", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, textColor=_LABEL, leading=12,
        ),
        "label": ParagraphStyle(
            "label", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, textColor=_LABEL, leading=11,
        ),
        "value": ParagraphStyle(
            "value", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=10, textColor=_INK, leading=13,
        ),
        "sectionHead": ParagraphStyle(
            "sectionHead", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.5, textColor=_INK, leading=12,
        ),
        "footer": ParagraphStyle(
            "footer", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=8.5, textColor=_LABEL, leading=11,
        ),
    }


def _letterhead(styles, teacher_name: str, studio_name: Optional[str] = None,
                logo_bytes: Optional[bytes] = None, doc_label: str = "Invoice"):
    """Logo + studio identity as one cohesive block, with a right-aligned
    document-type eyebrow. Reused by both the class invoice and (in future)
    other document types generated for the studio."""
    logo_cell = None
    if logo_bytes:
        try:
            img = RLImage(io.BytesIO(logo_bytes))
            ratio = (img.imageWidth or 1) / (img.imageHeight or 1)
            img.drawHeight = 17 * mm
            img.drawWidth = 17 * mm * ratio
            logo_cell = img
        except Exception:
            logo_cell = None

    identity_lines = []
    if studio_name:
        identity_lines.append(Paragraph(studio_name.upper(), styles["studio"]))
        identity_lines.append(Paragraph(f"{teacher_name} · Dance", styles["tagline"]))
    else:
        identity_lines.append(Paragraph(teacher_name, styles["studio"]))
        identity_lines.append(Paragraph("Dance Classes", styles["tagline"]))

    left_cell = [Paragraph(doc_label.upper(), styles["eyebrow"]), Spacer(1, 2 * mm)]
    if logo_cell:
        left_cell.append(logo_cell)

    right_cell = identity_lines

    header = Table([[left_cell, right_cell]], colWidths=[28 * mm, _PAGE_W - 28 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    els = [header, Spacer(1, 5 * mm)]
    els.append(Table([[""]], colWidths=[_PAGE_W], rowHeights=[1.1],
                      style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.1, _ACCENT)])))
    els.append(Spacer(1, 7 * mm))
    return els


def _meta_card(rows: list) -> Table:
    """A compact two-column info card (label left, value right per row),
    with a soft filled background so it reads as a distinct block rather
    than loose text floating on the page."""
    cells = []
    for label, value in rows:
        cells.append([
            Paragraph(label.upper(), ParagraphStyle(
                "mc-label", fontName="Helvetica", fontSize=8, textColor=_LABEL,
                leading=10,
            )),
            Paragraph(value, ParagraphStyle(
                "mc-value", fontName="Helvetica-Bold", fontSize=10, textColor=_INK, leading=13,
            )),
        ])
    tbl = Table(cells, colWidths=[32 * mm, _PAGE_W - 32 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _ACCENT_SOFT),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (0, -1), 6 * mm),
        ("LEFTPADDING", (1, 0), (1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return tbl


def _line_items_table(header_row: list, data_rows: list, col_widths: list,
                       numeric_cols: list) -> Table:
    """Shared table chrome: accent header, zebra striping, right-aligned
    numeric columns, warm hairline grid instead of a heavy black box."""
    rows = [header_row] + data_rows
    tbl = Table(rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("TEXTCOLOR", (0, 1), (-1, -1), _INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0, _ACCENT),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
    ]
    for col in numeric_cols:
        style.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    for i in range(1, len(rows)):
        if (i - 1) % 2 == 1:
            style.append(("BACKGROUND", (0, i), (-1, i), _ROW_TINT))
    tbl.setStyle(TableStyle(style))
    return tbl


def _summary_card(rows: list, emphasis_index: int, emphasis_color) -> Table:
    """Totals as a self-contained card with a filled band under the final
    (emphasized) row, so 'balance due' reads as the answer, not another
    line in a list."""
    cells = [[Paragraph(label, ParagraphStyle(
                  "sc-label", fontName="Helvetica", fontSize=10, textColor=_LABEL, leading=13)),
              Paragraph(value, ParagraphStyle(
                  "sc-value", fontName="Helvetica", fontSize=10.5, textColor=_INK,
                  leading=13, alignment=2))]
             for label, value in rows]
    emph_label, emph_value = rows[emphasis_index]
    cells[emphasis_index] = [
        Paragraph(emph_label, ParagraphStyle(
            "sc-elabel", fontName="Helvetica-Bold", fontSize=11, textColor=colors.white, leading=14)),
        Paragraph(emph_value, ParagraphStyle(
            "sc-evalue", fontName="Helvetica-Bold", fontSize=13, textColor=colors.white,
            leading=16, alignment=2)),
    ]
    tbl = Table(cells, colWidths=[60 * mm, 40 * mm], hAlign="RIGHT")
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


def _pdf_styles():
    """Back-compat shim for the old style dict shape some callers may still
    reference; new code should use _styles()."""
    return _styles()


def generate_invoice_pdf(teacher_name: str, student: dict, classes: list,
                         payments: list, summary: dict, start: Optional[str],
                         end: Optional[str], studio_name: Optional[str] = None,
                         logo_bytes: Optional[bytes] = None,
                         studio_contact: Optional[dict] = None) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    story.extend(_letterhead(styles, teacher_name, studio_name, logo_bytes, doc_label="Invoice"))

    now = datetime.now(timezone.utc)
    contact_line = " · ".join(filter(None, [student.get("email"), student.get("phone")]))
    story.append(_meta_card([
        ("Invoice #", f"INV-{now.strftime('%Y%m%d%H%M%S')}"),
        ("Date", now.strftime("%d %b %Y")),
        ("Billed to", student.get("name", "")),
        ("Contact", contact_line or "—"),
        ("Period", f"{start or 'All time'} – {end or 'Today'}"),
    ]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("CLASSES", styles["sectionHead"]))
    story.append(Spacer(1, 2.5 * mm))
    class_rows = [[
        c.get("class_date", ""), f"{c.get('hours', 0)}", f"{c.get('rate', 0)}",
        f"{c.get('amount', 0)}", c.get("notes") or "",
    ] for c in classes]
    story.append(_line_items_table(
        ["Date", "Hours", "Rate (INR/hr)", "Amount (INR)", "Notes"],
        class_rows, [26 * mm, 18 * mm, 32 * mm, 32 * mm, _PAGE_W - 108 * mm],
        numeric_cols=[1, 2, 3],
    ))
    story.append(Spacer(1, 7 * mm))

    if payments:
        story.append(Paragraph("PAYMENTS RECEIVED", styles["sectionHead"]))
        story.append(Spacer(1, 2.5 * mm))
        pay_rows = [[
            p.get("paid_on", ""), p.get("method") or "—", f"{p.get('amount', 0)}", p.get("notes") or "",
        ] for p in payments]
        story.append(_line_items_table(
            ["Date", "Method", "Amount (INR)", "Notes"],
            pay_rows, [28 * mm, 34 * mm, 32 * mm, _PAGE_W - 94 * mm],
            numeric_cols=[2],
        ))
        story.append(Spacer(1, 7 * mm))

    balance_due = summary.get("balance_due", 0)
    is_settled = balance_due <= 0
    story.append(_summary_card(
        [
            ("Total billed", f"INR {summary.get('total_billed', 0)}"),
            ("Total paid", f"INR {summary.get('total_paid', 0)}"),
            ("Balance settled" if is_settled else "Balance due",
             f"INR {abs(balance_due)}"),
        ],
        emphasis_index=2,
        emphasis_color=_PAID if is_settled else _DUE,
    ))
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
        styles["footer"]))

    social_line = _social_links_line(studio_contact)
    if social_line:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(social_line, styles["footer"]))

    doc.build(story)
    buf.seek(0)
    return buf.read()


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
    return " · ".join(bits) if bits else None


def generate_tour_expense_pdf(tour: dict, expenses: list) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    story.append(Paragraph("TOUR EXPENSES", styles["eyebrow"]))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(tour.get("name", ""), styles["studio"]))
    period = f"{tour.get('start_date', '')} – {tour.get('end_date', '')}"
    story.append(Paragraph(period, styles["tagline"]))
    story.append(Spacer(1, 3 * mm))
    story.append(Table([[""]], colWidths=[_PAGE_W], rowHeights=[1.1],
                        style=TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.1, _ACCENT)])))
    story.append(Spacer(1, 7 * mm))

    total = sum(float(e.get("amount", 0)) for e in expenses)
    rows = [[
        e.get("expense_date", ""), e.get("category", ""), f"{float(e.get('amount', 0)):.2f}",
        e.get("notes") or "",
    ] for e in expenses]
    story.append(_line_items_table(
        ["Date", "Category", "Amount (INR)", "Notes"],
        rows, [28 * mm, 40 * mm, 30 * mm, _PAGE_W - 98 * mm],
        numeric_cols=[2],
    ))
    story.append(Spacer(1, 7 * mm))
    story.append(_summary_card(
        [("Total", f"INR {total:.2f}")], emphasis_index=0, emphasis_color=_ACCENT,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
