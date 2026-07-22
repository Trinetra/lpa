"""Email dispatch + templates (invoice send, password reset).

Sends directly via the Resend API. Reads ``RESEND_API_KEY``,
``RESEND_FROM``, and ``EMAIL_FROM_NAME`` from environment.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from db import db

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


def _email_key() -> Optional[str]:
    return os.environ.get("RESEND_API_KEY")


def _from_address() -> str:
    return os.environ.get("RESEND_FROM", "onboarding@resend.dev")


def _from_name() -> str:
    return os.environ.get("EMAIL_FROM_NAME", "Studio Ledger")


def _backend_url() -> str:
    return os.environ.get("BACKEND_URL", "").rstrip("/")


def build_invoice_email_html(inv: dict, public_link: str, pdf_link: str,
                              teacher_name: str, personal_note: Optional[str]) -> str:
    student = inv.get("student_snapshot", {})
    summary = inv.get("summary", {})
    period = f"{inv.get('start_date') or 'All time'} — {inv.get('end_date') or 'today'}"
    note_html = ""
    if personal_note:
        safe = personal_note.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        note_html = (
            f'<tr><td style="padding:8px 0;font-family:Arial,sans-serif;'
            f'font-size:14px;color:#2c2926;font-style:italic">{safe}</td></tr>'
        )
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">Invoice from</div>
        <div style="font-size:24px;color:#d48464;font-weight:700;margin-bottom:24px">{teacher_name}</div>
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          Hi {student.get("name") or "there"},<br><br>
          Here's your invoice for dance classes ({period}).
        </div>
        {note_html}
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;border-top:1px solid #eadfd1;border-bottom:1px solid #eadfd1">
          <tr><td style="padding:12px 0;font-size:14px;color:#666">Total billed</td><td align="right" style="padding:12px 0;font-size:14px;color:#2c2926">₹ {summary.get("total_billed", 0)}</td></tr>
          <tr><td style="padding:0 0 12px;font-size:14px;color:#666">Total paid</td><td align="right" style="padding:0 0 12px;font-size:14px;color:#7c9082">₹ {summary.get("total_paid", 0)}</td></tr>
          <tr><td style="padding:12px 0;font-size:16px;color:#b85c5c;font-weight:700;border-top:1px solid #eadfd1">Balance due</td><td align="right" style="padding:12px 0;font-size:16px;color:#b85c5c;font-weight:700;border-top:1px solid #eadfd1">₹ {summary.get("balance_due", 0)}</td></tr>
        </table>
        <table cellpadding="0" cellspacing="0"><tr>
          <td style="padding-right:8px"><a href="{public_link}" style="display:inline-block;background:#d48464;color:#1a1816;text-decoration:none;padding:12px 22px;border-radius:999px;font-weight:600;font-size:14px">View invoice</a></td>
          <td><a href="{pdf_link}" style="display:inline-block;background:#ffffff;color:#2c2926;text-decoration:none;padding:12px 22px;border-radius:999px;font-weight:600;font-size:14px;border:1px solid #eadfd1">Download PDF</a></td>
        </tr></table>
        <div style="font-size:12px;color:#a89886;margin-top:24px">Thank you for learning with us.</div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()


def build_invoice_email_payload(inv: dict, invoice_id: str, to_email: str,
                                 public_link: str, message: Optional[str],
                                 reply_to: Optional[str]) -> dict:
    backend = _backend_url()
    api_pdf_link = (
        f"{backend}/api/invoices/{invoice_id}/pdf?token={inv['share_token']}"
        if backend else ""
    )
    teacher = inv.get("teacher_name") or _from_name()
    html = build_invoice_email_html(inv, public_link, api_pdf_link, teacher, message)
    payload = {
        "to": [to_email],
        "subject": f"Invoice from {teacher}",
        "html": html,
        "from_name": _from_name(),
    }
    if reply_to:
        payload["contact_email"] = reply_to
    return payload


_CURRENCY_SYMBOLS = {"INR": "₹", "EUR": "€", "USD": "$", "GBP": "£"}


def build_tour_invoice_email_html(invoice: dict, teacher_name: str, pdf_link: str) -> str:
    symbol = _CURRENCY_SYMBOLS.get(invoice.get("currency", "INR"), invoice.get("currency", ""))
    amount = invoice.get("amount", 0)
    amount_str = f"{symbol}{amount:,.0f}" if float(amount) == int(amount) else f"{symbol}{amount:,.2f}"
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#fffdf9;padding:24px 0;font-family:Georgia,'Times New Roman',serif">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e4d9c8;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#8a6d3b;text-transform:uppercase;margin-bottom:6px;font-family:Arial,sans-serif">Invoice from</div>
        <div style="font-size:24px;color:#7a1f2b;font-weight:700;margin-bottom:24px">{teacher_name}</div>
        <div style="font-size:15px;color:#2b2b2b;line-height:1.5;font-family:Arial,sans-serif">
          Dear {invoice.get("recipient_name") or "there"},<br><br>
          Please find attached the invoice for {invoice.get("description", "our engagement")}.
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;border-top:1px solid #e4d9c8;border-bottom:1px solid #e4d9c8">
          <tr><td style="padding:12px 0;font-size:16px;color:#7a1f2b;font-weight:700;font-family:Arial,sans-serif">Amount due</td>
              <td align="right" style="padding:12px 0;font-size:16px;color:#7a1f2b;font-weight:700;font-family:Arial,sans-serif">{amount_str}</td></tr>
        </table>
        <table cellpadding="0" cellspacing="0"><tr>
          <td><a href="{pdf_link}" style="display:inline-block;background:#7a1f2b;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:6px;font-weight:600;font-size:14px;font-family:Arial,sans-serif">Download invoice</a></td>
        </tr></table>
        <div style="font-size:12px;color:#8a6d3b;margin-top:24px;font-family:Arial,sans-serif">Thank you for the opportunity to perform.</div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()


async def dispatch_email(payload: dict) -> dict:
    key = _email_key()
    if not key:
        raise RuntimeError("No email transport configured (set RESEND_API_KEY)")

    rs_body = {
        "from": f"{_from_name()} <{_from_address()}>",
        "to": payload["to"],
        "subject": payload["subject"],
        "html": payload["html"],
    }
    reply_to = payload.get("contact_email")
    if reply_to:
        rs_body["reply_to"] = reply_to
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json=rs_body,
        )
    resp.raise_for_status()
    return resp.json()


async def mark_invoice_sent(invoice_id: str, to_email: str):
    await db.invoices.update_one(
        {"invoice_id": invoice_id},
        {"$set": {
            "last_sent_to": to_email,
            "last_sent_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


async def send_password_reset_email(to_email: str, name: str, reset_link: str):
    key = _email_key()
    if not key:
        logger.warning(f"Password reset requested but no email key set. Link: {reset_link}")
        return
    from_name = _from_name()
    html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">Password reset</div>
        <div style="font-size:22px;color:#d48464;font-weight:700;margin-bottom:20px">{from_name}</div>
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          Hi {name or "there"},<br><br>
          We received a request to reset your password. Click the button below to choose a new one.
          This link expires in 60 minutes.
        </div>
        <div style="margin:24px 0"><a href="{reset_link}" style="display:inline-block;background:#d48464;color:#1a1816;text-decoration:none;padding:12px 26px;border-radius:999px;font-weight:600;font-size:14px">Reset password</a></div>
        <div style="font-size:12px;color:#a89886">If you didn't request this, you can safely ignore this email.</div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()
    payload = {
        "to": [to_email],
        "subject": f"Reset your {from_name} password",
        "html": html,
        "from_name": from_name,
    }
    try:
        await dispatch_email(payload)
    except Exception as e:
        logger.error(f"Password reset email failed: {e}")
