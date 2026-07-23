"""Invoice PDF generation. Pure functions — no database or network."""

import io
import os
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import qrcode
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

_PAGE_W = 174 * mm  # A4 width minus 18mm margins each side
_RUPEE = "₹"
_CURRENCY_SYMBOLS = {"INR": "₹", "EUR": "€", "USD": "$", "GBP": "£"}


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


def _fmt_money(n, currency: str = "INR") -> str:
    try:
        v = float(n)
    except (TypeError, ValueError):
        v = 0.0
    symbol = _CURRENCY_SYMBOLS.get(currency, currency + " ")
    if v == int(v):
        return f"{symbol}{int(v):,}"
    return f"{symbol}{v:,.2f}"


def upi_qr_bytes(vpa: str, payee_name: str, amount: float) -> Optional[bytes]:
    """Public entry point for the shared web invoice page, which shows the
    same scannable UPI QR as the PDF."""
    return _upi_qr_bytes(vpa, payee_name, amount)


def _upi_qr_bytes(vpa: str, payee_name: str, amount: float) -> Optional[bytes]:
    """Generate a scannable UPI payment QR as PNG bytes, or None on failure.
    UPI deep-link format: upi://pay?pa=<vpa>&pn=<name>&am=<amount>&cu=INR"""
    try:
        uri = (
            f"upi://pay?pa={quote(vpa)}&pn={quote(payee_name)}"
            f"&am={amount:.2f}&cu=INR"
        )
        img = qrcode.make(uri, box_size=4, border=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _letterhead(styles, teacher_name: str, studio_name: Optional[str] = None,
                logo_bytes: Optional[bytes] = None, doc_label: str = "Invoice"):
    """Centered logo (large), the document label (e.g. "Invoice") centered
    beneath it — no studio-name caption or teacher tagline here, per the
    reference letterhead."""
    els = []

    if logo_bytes:
        try:
            img = RLImage(io.BytesIO(logo_bytes))
            ratio = (img.imageWidth or 1) / (img.imageHeight or 1)
            img.drawHeight = 34 * mm
            img.drawWidth = 34 * mm * ratio
            img.hAlign = "CENTER"
            els.append(img)
            els.append(Spacer(1, 4 * mm))
        except Exception:
            pass

    els.append(Paragraph(doc_label.upper(), ParagraphStyle(
        "doc-label", parent=styles["eyebrow"], fontSize=16, leading=19,
    )))

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
        # Header row: just enough padding to bleed slightly past the text
        # (~10px), not the same generous padding as body rows — a thick
        # header band read as heavy-handed.
        ("TOPPADDING", (0, 0), (-1, 0), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2.6),
        ("TOPPADDING", (0, 1), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5.5),
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
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("BACKGROUND", (0, emphasis_index), (-1, emphasis_index), emphasis_color),
        ("LEFTPADDING", (0, emphasis_index), (0, emphasis_index), 4 * mm),
        ("RIGHTPADDING", (0, emphasis_index), (-1, emphasis_index), 4 * mm),
        ("LINEABOVE", (0, emphasis_index), (-1, emphasis_index), 0.4, _RULE),
    ]
    tbl.setStyle(TableStyle(style))
    return tbl


def _totals_table(styles, rows: list) -> Table:
    """Equal-weight totals, one row per currency — used when a tour's
    expenses span more than one currency and no single row is "the answer"
    the way a due/paid amount is, so no row gets emphasis banding."""
    label_style = ParagraphStyle("tt-label", parent=styles["label"], fontName=_FONT_BOLD,
                                  fontSize=10.5, textColor=_INK, leading=13)
    value_style = ParagraphStyle("tt-value", parent=styles["label"], fontName=_FONT_BOLD,
                                  fontSize=10.5, textColor=_INK, leading=13, alignment=2)
    cells = [[Paragraph(label, label_style), Paragraph(value, value_style)] for label, value in rows]
    tbl = Table(cells, colWidths=[65 * mm, 45 * mm], hAlign="RIGHT")
    tbl.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LINEABOVE", (0, 0), (-1, 0), 0.4, _RULE),
    ]))
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
    else:
        summary_rows.append(("Final Amount Due", _fmt_money(balance_due)))

    summary_tbl = _summary_card(styles, summary_rows, emphasis_index=len(summary_rows) - 1,
                                 emphasis_color=_MAROON)

    # UPI QR code — only meaningful for domestic (INR) dance-class invoices;
    # a foreign/tour invoice recipient can't pay via UPI, so this is never
    # shown there (generate_tour_invoice_pdf doesn't call this at all).
    upi_vpa = (studio_contact or {}).get("contact_upi")
    qr_bytes = _upi_qr_bytes(upi_vpa, teacher_name, balance_due) if (upi_vpa and balance_due > 0) else None
    if qr_bytes:
        qr_img = RLImage(io.BytesIO(qr_bytes))
        qr_img.drawWidth = 26 * mm
        qr_img.drawHeight = 26 * mm
        qr_caption = Paragraph("Scan to pay via UPI", ParagraphStyle(
            "qr-caption", parent=styles["footer"], fontSize=7.5, alignment=1))
        # QR + caption as their own single-column table so the caption
        # actually centers under the QR image, rather than the whole block
        # being left-aligned in the outer row (which left-hung the narrower
        # caption text against the wider image).
        qr_block = Table([[qr_img], [qr_caption]], colWidths=[26 * mm])
        qr_block.setStyle(TableStyle([
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 1),
        ]))

        row = Table([[qr_block, summary_tbl]], colWidths=[40 * mm, _PAGE_W - 40 * mm])
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "LEFT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(row)
    else:
        story.append(summary_tbl)
    story.append(Spacer(1, 7 * mm))

    story.append(Paragraph(
        "Thank you for learning with us. Please remit any balance at your earliest convenience.",
        styles["footer"]))

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

    # Expenses on a tour commonly span more than one currency (flights in
    # USD, local transport in GBP, etc.) — summing them into one blended
    # number would be meaningless, so totals are grouped per currency.
    totals_by_currency = {}
    rows = []
    for e in expenses:
        currency = e.get("currency", "INR")
        amount = float(e.get("amount", 0))
        totals_by_currency[currency] = totals_by_currency.get(currency, 0) + amount
        rows.append([
            _fmt_date(e.get("expense_date")), e.get("category", ""),
            _fmt_money(amount, currency), e.get("notes") or "",
        ])
    story.append(_line_items_table(
        styles, ["Date", "Category", "Amount", "Notes"],
        rows, [30 * mm, 40 * mm, 30 * mm, _PAGE_W - 100 * mm],
    ))
    story.append(Spacer(1, 7 * mm))
    total_rows = [(f"Total ({c})", _fmt_money(t, c)) for c, t in sorted(totals_by_currency.items())]
    if len(total_rows) == 1:
        story.append(_summary_card(
            styles, total_rows, emphasis_index=0, emphasis_color=_MAROON,
        ))
    elif total_rows:
        story.append(_totals_table(styles, total_rows))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def generate_tour_invoice_pdf(teacher_name: str, studio_name: Optional[str],
                               logo_bytes: Optional[bytes], invoice: dict,
                               studio_contact: Optional[dict] = None) -> bytes:
    """Simpler layout than the class invoice — a single description/amount
    line, no per-class table, since a tour invoice bills a performance or
    engagement as a whole rather than itemized hours."""
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    story.extend(_letterhead(styles, teacher_name, studio_name, logo_bytes, doc_label="Invoice"))

    currency = invoice.get("currency", "INR")
    story.append(_meta_card(styles, [
        ("Invoice #", invoice.get("invoice_number") or "—"),
        ("Date", _fmt_date(invoice.get("invoice_date"))),
        ("Billed to", invoice.get("recipient_name", "")),
        ("Contact", invoice.get("recipient_email") or "—"),
    ]))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("DESCRIPTION", styles["sectionHead"]))
    story.append(Spacer(1, 2.5 * mm))
    story.append(Paragraph(invoice.get("description", ""), ParagraphStyle(
        "desc", parent=styles["label"], fontSize=10.5, textColor=_INK, leading=15)))
    story.append(Spacer(1, 8 * mm))

    paid = invoice.get("paid", False)
    amount_label = "Paid" if paid else "Amount Due"
    story.append(Paragraph(amount_label.upper(), styles["sectionHead"]))
    story.append(Spacer(1, 2.5 * mm))
    story.append(Paragraph(_fmt_money(invoice.get("amount", 0), currency), ParagraphStyle(
        "amountDue", parent=styles["label"], fontSize=10.5, textColor=_INK, leading=15)))
    story.append(Spacer(1, 8 * mm))

    if studio_contact and not paid:
        if currency == "INR":
            # UPI/phone are India-specific — meaningful for a domestic payer.
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
        else:
            # A UPI ID can't receive foreign currency — show bank transfer
            # details instead (the account number is the one thing a payer
            # actually needs; SWIFT identifies the bank internationally).
            bank_name = studio_contact.get("bank_name")
            account_number = studio_contact.get("bank_account_number")
            swift_code = studio_contact.get("bank_swift_code")
            if bank_name or account_number or swift_code:
                bank_lines = [f'<font name="{_FONT_BOLD}" size="10">My bank details</font>']
                if teacher_name:
                    bank_lines.append(f"Name: {teacher_name}")
                if bank_name:
                    bank_lines.append(f"Bank Name: {bank_name}")
                if account_number:
                    bank_lines.append(f"Account Number: <b>{account_number}</b>")
                if swift_code:
                    bank_lines.append(f"SWIFT: {swift_code}")
                story.append(Paragraph("<br/>".join(bank_lines), ParagraphStyle(
                    "bankDetails", parent=styles["label"], fontSize=10, textColor=_INK, leading=15)))
                story.append(Spacer(1, 5 * mm))
            if studio_contact.get("contact_email"):
                story.append(Paragraph(f"<b>Contact:</b> {studio_contact['contact_email']}", styles["label"]))
                story.append(Spacer(1, 4 * mm))

    story.append(Paragraph(
        "Thank you for the opportunity to perform. Please remit payment at your earliest convenience.",
        styles["footer"]))

    story.extend(_footer(styles, teacher_name, studio_contact))

    doc.build(story)
    buf.seek(0)
    return buf.read()
