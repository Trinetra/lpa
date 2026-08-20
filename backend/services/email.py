"""Email dispatch + templates (invoice send, password reset).

Sends directly via the Resend API. Reads ``RESEND_API_KEY``,
``RESEND_FROM``, and ``EMAIL_FROM_NAME`` from environment.
"""

import logging
import os
import random
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
    return os.environ.get("EMAIL_FROM_NAME", "Pravaaha Center for Movement")


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
    bcc = payload.get("bcc")
    if bcc:
        rs_body["bcc"] = bcc
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


_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_change_request_notification_html(student_name: str, req: dict, review_link: str) -> str:
    from_name = _from_name()
    kind = "cancel" if req.get("type") == "cancel" else "reschedule"
    scope = "just this class" if req.get("scope") == "one_time" else "permanently, going forward"

    detail_html = ""
    if req.get("type") == "reschedule" and req.get("requested_day_of_week") is not None:
        day = _DAY_NAMES[req["requested_day_of_week"]]
        detail_html = (
            f'<div style="margin-top:10px;font-size:15px;color:#2c2926">'
            f'Requested: <b>{day} {req.get("requested_start_time")}–{req.get("requested_end_time")}</b></div>'
        )

    reason_html = ""
    if req.get("reason"):
        safe = req["reason"].replace("<", "&lt;").replace(">", "&gt;")
        reason_html = f'<div style="margin-top:10px;font-size:14px;color:#2c2926;font-style:italic">"{safe}"</div>'

    link_html = ""
    if review_link:
        link_html = (
            f'<div style="margin:24px 0"><a href="{review_link}" style="display:inline-block;'
            f'background:#d48464;color:#1a1816;text-decoration:none;padding:12px 26px;'
            f'border-radius:999px;font-weight:600;font-size:14px">Review request</a></div>'
        )

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">Student portal</div>
        <div style="font-size:22px;color:#d48464;font-weight:700;margin-bottom:16px">New {kind} request</div>
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          <b>{student_name}</b> is asking to {kind} a class — {scope}.
        </div>
        {detail_html}
        {reason_html}
        {link_html}
        <div style="font-size:12px;color:#a89886;margin-top:8px">This needs your approval before anything changes.</div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()


async def send_change_request_email(to_email: str, student_name: str, req: dict, review_link: str):
    key = _email_key()
    if not key:
        logger.warning(f"Change request notification skipped (no email key). Student={student_name}, link={review_link}")
        return
    html = build_change_request_notification_html(student_name, req, review_link)
    kind = "Cancellation" if req.get("type") == "cancel" else "Reschedule"
    payload = {
        "to": [to_email],
        "subject": f"{kind} request from {student_name}",
        "html": html,
        "from_name": _from_name(),
    }
    try:
        await dispatch_email(payload)
    except Exception as e:
        logger.error(f"Change request notification email failed: {e}")


_GREETINGS = ["beautiful", "gorgeous", "superstar", "lovely", "Sundari", "azhagi"]


def _fmt_time_12h_short(t: str) -> str:
    h, m = t.split(":")
    h, m = int(h), int(m)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{period}"


def build_unlogged_classes_html(items: list, classes_link: str) -> str:
    """items: list of {student_name, date_label, start_time, link} for every
    class that ended today without a matching logged entry."""
    greeting = random.choice(_GREETINGS)

    rows_html = ""
    for item in items:
        rows_html += f"""
        <tr>
          <td style="padding:14px 0;border-top:1px solid #eadfd1;font-size:15px;color:#2c2926;font-family:Arial,sans-serif">
            <b>{item['student_name']}</b> &middot; {item['date_label']} at {item['start_time']}
          </td>
          <td align="right" style="padding:14px 0;border-top:1px solid #eadfd1">
            <a href="{item['link']}" style="display:inline-block;background:#d48464;color:#1a1816;
                text-decoration:none;padding:8px 18px;border-radius:999px;font-weight:600;font-size:13px;
                font-family:Arial,sans-serif;white-space:nowrap">Update it</a>
          </td>
        </tr>"""

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">End of day check-in</div>
        <div style="font-size:22px;color:#d48464;font-weight:700;margin-bottom:16px">Hey {greeting}!</div>
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          Looks like {"a class" if len(items) == 1 else f"{len(items)} classes"} from today {"hasn't" if len(items) == 1 else "haven't"} been logged yet — a quick tap below and you're done.
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:16px">
          {rows_html}
        </table>
        <div style="margin:26px 0 0 0"><a href="{classes_link}" style="display:inline-block;background:#ffffff;color:#2c2926;
            text-decoration:none;padding:12px 26px;border-radius:999px;font-weight:600;font-size:14px;
            border:1px solid #eadfd1">Open Classes</a></div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()


async def send_unlogged_classes_email(to_email: str, items: list, classes_link: str):
    key = _email_key()
    if not key:
        logger.warning(f"Unlogged-classes reminder skipped (no email key). {len(items)} item(s).")
        return
    html = build_unlogged_classes_html(items, classes_link)
    count_label = "a class" if len(items) == 1 else f"{len(items)} classes"
    payload = {
        "to": [to_email],
        "subject": f"Don't forget — {count_label} from today still need logging",
        "html": html,
        "from_name": _from_name(),
    }
    try:
        await dispatch_email(payload)
    except Exception as e:
        logger.error(f"Unlogged-classes reminder email failed: {e}")


async def send_student_invite_email(to_email: str, name: str, teacher_name: str, invite_link: str):
    key = _email_key()
    if not key:
        logger.warning(f"Student portal invite requested but no email key set. Link: {invite_link}")
        return
    from_name = _from_name()
    html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">You're invited</div>
        <div style="font-size:22px;color:#d48464;font-weight:700;margin-bottom:20px">{teacher_name or from_name} student portal</div>
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          Hi {name or "there"},<br><br>
          {teacher_name or from_name} has set up a student portal where you can check your class schedule,
          see your dues, track your progress, keep your own notes, and request a change to a class
          (at least 24 hours ahead). Click below to sign in and set up your password — this link works once
          and expires in 7 days.
        </div>
        <div style="margin:24px 0"><a href="{invite_link}" style="display:inline-block;background:#d48464;color:#1a1816;text-decoration:none;padding:12px 26px;border-radius:999px;font-weight:600;font-size:14px">Set up my account</a></div>
        <div style="font-size:12px;color:#a89886">After this, you'll sign in with your email and password.</div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()
    payload = {
        "to": [to_email],
        "subject": f"You're invited to the {teacher_name or from_name} student portal",
        "html": html,
        "from_name": from_name,
    }
    try:
        await dispatch_email(payload)
    except Exception as e:
        logger.error(f"Student portal invite email failed: {e}")


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


async def send_event_invite_email(to_email: str, name: str, event_name: str, teacher_name: str,
                                   zoom_meeting_id: Optional[str], zoom_passcode: Optional[str],
                                   start_date: Optional[str], time_str: Optional[str]):
    key = _email_key()
    if not key:
        logger.warning(f"Event invite requested but no email key set. Event: {event_name}, Zoom: {zoom_meeting_id}")
        return
    from_name = _from_name()
    when = " ".join(filter(None, [start_date, time_str])) or "the scheduled time"
    zoom_lines = ""
    if zoom_meeting_id:
        zoom_lines += f'<div style="font-size:15px;color:#2c2926;margin-top:4px">Meeting ID: <b>{zoom_meeting_id}</b></div>'
    if zoom_passcode:
        zoom_lines += f'<div style="font-size:15px;color:#2c2926;margin-top:4px">Passcode: <b>{zoom_passcode}</b></div>'
    html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">You're confirmed</div>
        <div style="font-size:22px;color:#d48464;font-weight:700;margin-bottom:20px">{event_name}</div>
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          Hi {name or "there"},<br><br>
          Your spot for {event_name} with {teacher_name or from_name} is confirmed. Here are your Zoom details
          for {when}:
        </div>
        <div style="margin:20px 0;padding:16px;background:#f5efe8;border-radius:8px">{zoom_lines}</div>
        <div style="font-size:12px;color:#a89886">See you there!</div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()
    payload = {
        "to": [to_email],
        "subject": f"You're confirmed for {event_name} — Zoom details inside",
        "html": html,
        "from_name": from_name,
    }
    await dispatch_email(payload)


def _format_event_when(start_date: Optional[str], time_str: Optional[str]) -> str:
    """'2026-07-13' + '6:00 PM IST' -> 'Sunday, 13th July 2026 at 6:00 PM IST'."""
    if not start_date:
        return "soon"
    try:
        d = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return " ".join(filter(None, [start_date, time_str])) or "soon"
    day = d.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    when = f"{d.strftime('%A')}, {day}{suffix} {d.strftime('%B %Y')}"
    if time_str:
        when += f" at {time_str}"
    return when


async def send_event_announcement_email(to_email: str, name: str, event_name: str, teacher_name: str,
                                         event_link: str, start_date: Optional[str], time_str: Optional[str],
                                         description: Optional[str] = None, image_event_id: Optional[str] = None,
                                         track_pixel_url: Optional[str] = None, track_click_url: Optional[str] = None):
    """Invites a past CRM contact to register for a new/upcoming event —
    distinct from send_event_invite_email, which confirms Zoom details to
    someone who has already registered and been approved for a specific
    event. This one just points at the public registration page, and
    includes the event's own poster image + description since that's what
    actually sells someone on attending."""
    key = _email_key()
    if not key:
        logger.warning(f"Event announcement requested but no email key set. Event: {event_name}, Link: {event_link}")
        return
    from_name = _from_name()
    when = _format_event_when(start_date, time_str)
    image_html = ""
    if image_event_id:
        image_url = f"{_backend_url()}/api/events/{image_event_id}/image"
        image_html = f'<img src="{image_url}" alt="{event_name}" width="456" style="width:100%;max-width:456px;border-radius:8px;display:block;margin-bottom:20px" />'
    description_html = ""
    if description:
        description_html = f'<div style="font-size:14px;color:#2c2926;line-height:1.5;white-space:pre-wrap;margin-top:16px">{description}</div>'
    register_link = track_click_url or event_link
    pixel_html = f'<img src="{track_pixel_url}" alt="" width="1" height="1" style="display:block;border:0" />' if track_pixel_url else ""
    html = f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5efe8;padding:24px 0;font-family:Arial,sans-serif">
  <tr><td align="center">
    <table width="520" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #eadfd1;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#a89886;text-transform:uppercase;margin-bottom:6px">New event</div>
        <div style="font-size:22px;color:#d48464;font-weight:700;margin-bottom:20px">{event_name}</div>
        {image_html}
        <div style="font-size:15px;color:#2c2926;line-height:1.5">
          Hi {name or "there"},<br><br>
          We would love to have you at {event_name}, happening on {when}.
          Click below to register.
        </div>
        {description_html}
        <div style="margin:24px 0"><a href="{register_link}" style="display:inline-block;background:#d48464;color:#1a1816;text-decoration:none;padding:12px 26px;border-radius:999px;font-weight:600;font-size:14px">Register now</a></div>
      </td></tr>
    </table>
  </td></tr>
</table>
{pixel_html}
""".strip()
    payload = {
        "to": [to_email],
        "subject": f"You're invited: {event_name}",
        "html": html,
        "from_name": from_name,
    }
    await dispatch_email(payload)
