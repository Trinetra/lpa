"""Email dispatch + templates (invoice send, password reset).

Uses the Emergent-managed Resend proxy at ``integrations.emergentagent.com``.
Reads ``EMERGENT_EMAIL_KEY`` and ``EMAIL_FROM_NAME`` from environment.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

from db import db

logger = logging.getLogger(__name__)

EMAIL_BASE_URL = "https://integrations.emergentagent.com"
RESEND_URL = "https://api.resend.com/emails"


def _email_key() -> Optional[str]:
    # Prefer the Emergent proxy key (works only inside Emergent). Fall back to a
    # user-supplied Resend key for self-hosted deployments.
    return os.environ.get("EMERGENT_EMAIL_KEY") or os.environ.get("RESEND_API_KEY")


def _use_direct_resend() -> bool:
    return not os.environ.get("EMERGENT_EMAIL_KEY") and bool(os.environ.get("RESEND_API_KEY"))


def _from_address() -> str:
    return os.environ.get("RESEND_FROM", "onboarding@resend.dev")


def _from_name() -> str:
    return os.environ.get("EMAIL_FROM_NAME", "Studio Ledger")


def _origin_from_public_link(public_link: str) -> str:
    if "/invoice/" not in public_link:
        return ""
    return public_link.split("/invoice/")[0]


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
    origin = _origin_from_public_link(public_link)
    api_pdf_link = (
        f"{origin}/api/invoices/{invoice_id}/pdf?token={inv['share_token']}"
        if origin else ""
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


async def dispatch_email(payload: dict) -> dict:
    key = _email_key()
    if not key:
        raise RuntimeError("No email transport configured (set EMERGENT_EMAIL_KEY or RESEND_API_KEY)")

    if _use_direct_resend():
        # Direct Resend API — used when self-hosted on a VPS.
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

    # Emergent-managed Resend proxy — used inside the preview environment.
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            f"{EMAIL_BASE_URL}/api/v1/email/send",
            headers={"X-Email-Key": key},
            json=payload,
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
