"""30-minutes-before class reminder emails, sent directly to each scheduled
student — independent of Google Calendar, since a Calendar reminder override
only ever notifies the event's organizer, never invited guests. Triggered by
a host cron job hitting the reminders/cron endpoint every few minutes (see
server.py), not by an in-process scheduler.
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from db import db
from services import email as email_service

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")  # schedule_blocks times are entered in IST — all classes are in India.
REMINDER_MINUTES_BEFORE = 30
# Cron runs every ~5 min; a wider match window than that keeps a block from
# being missed if a run is skipped or delayed, without risking a double-send
# for the same run (guarded separately by the reminders_sent dedupe below).
WINDOW_MINUTES = 7


def _zoom_link(zoom_meeting_id: Optional[str]) -> Optional[str]:
    if not zoom_meeting_id:
        return None
    digits = "".join(ch for ch in zoom_meeting_id if ch.isdigit())
    return f"https://zoom.us/j/{digits}" if digits else None


def _fmt_time_12h(t: str) -> str:
    h, m = t.split(":")
    h, m = int(h), int(m)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {period}"


def _reminder_email_html(student_name: str, teacher_name: str, studio_name: Optional[str],
                          start_time: str, end_time: str, zoom_link: Optional[str]) -> str:
    brand = studio_name or teacher_name
    time_range = f"{_fmt_time_12h(start_time)} – {_fmt_time_12h(end_time)} IST"

    zoom_html = ""
    if zoom_link:
        zoom_html = f"""
        <table cellpadding="0" cellspacing="0" style="margin-top:22px"><tr>
          <td><a href="{zoom_link}" style="display:inline-block;background:#7a1f2b;color:#ffffff;
              text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:600;font-size:14px;
              font-family:Arial,sans-serif">Join Zoom Meeting</a></td>
        </tr></table>
        """

    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#fffdf9;padding:24px 0;font-family:Georgia,'Times New Roman',serif">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e4d9c8;border-radius:8px;padding:32px">
      <tr><td>
        <div style="font-size:12px;letter-spacing:2px;color:#8a6d3b;text-transform:uppercase;
            margin-bottom:6px;font-family:Arial,sans-serif">Class reminder</div>
        <div style="font-size:24px;color:#7a1f2b;font-weight:700;margin-bottom:20px">{brand}</div>
        <div style="font-size:15px;color:#2b2b2b;line-height:1.6;font-family:Arial,sans-serif">
          Hi {student_name or "there"},<br><br>
          Just a heads-up — your class starts in about <b>{REMINDER_MINUTES_BEFORE} minutes</b>.
        </div>
        <table width="100%" cellpadding="0" cellspacing="0" style="margin:22px 0;background:#fbf5ec;
            border:1px solid #e4d9c8;border-radius:6px">
          <tr><td style="padding:16px 20px;font-family:Arial,sans-serif">
            <div style="font-size:11px;letter-spacing:1px;color:#8a6d3b;text-transform:uppercase;margin-bottom:4px">Today</div>
            <div style="font-size:19px;color:#2b2b2b;font-weight:700">{time_range}</div>
          </td></tr>
        </table>
        {zoom_html}
        <div style="font-size:13px;color:#8a6d3b;margin-top:26px;font-family:Arial,sans-serif;font-style:italic">
          See you soon!<br/>{teacher_name}
        </div>
      </td></tr>
    </table>
  </td></tr>
</table>
""".strip()


async def _send_block_reminders(owner_id: str, block: dict, teacher_name: str,
                                 studio_name: Optional[str], zoom_link: Optional[str],
                                 today_str: str) -> dict:
    sent, skipped = 0, 0
    for sid in block.get("student_ids", []):
        student = await db.students.find_one({"_id": _oid(sid), "owner_id": owner_id})
        if not student or not student.get("email"):
            skipped += 1
            continue

        # Reserve the dedupe slot *before* sending — the unique index makes
        # this atomic, so two overlapping cron runs can't both pass this
        # check and double-send. If the send then fails, the reservation is
        # rolled back so a later run retries instead of silently giving up.
        dedupe_key = {"block_id": str(block["_id"]), "date": today_str, "student_id": sid}
        try:
            await db.reminders_sent.insert_one({
                **dedupe_key,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            continue  # duplicate key — already sent (or being sent) by another run

        html = _reminder_email_html(
            student.get("name"), teacher_name, studio_name,
            block["start_time"], block["end_time"], zoom_link,
        )
        try:
            await email_service.dispatch_email({
                "to": [student["email"]],
                "subject": f"Class reminder — starts at {block['start_time']} IST",
                "html": html,
            })
            sent += 1
        except Exception as e:
            logger.error(f"Reminder email failed for student {sid}: {e}")
            await db.reminders_sent.delete_one(dedupe_key)
            skipped += 1
    return {"sent": sent, "skipped": skipped}


def _oid(sid: str):
    from bson import ObjectId
    return ObjectId(sid)


async def send_due_reminders(owner_id: str) -> dict:
    """Find today's schedule blocks starting in ~30 minutes and email every
    student on that block who hasn't already been reminded today. Safe to
    call repeatedly (e.g. every 5 min via cron) — already-reminded
    block/date/student combinations are skipped via reminders_sent."""
    from bson import ObjectId

    user = await db.users.find_one({"_id": ObjectId(owner_id)})
    if not user:
        return {"ok": False, "reason": "User not found"}

    now_ist = datetime.now(IST)
    today_ist = now_ist.date()
    today_str = today_ist.isoformat()
    weekday = today_ist.weekday()  # 0=Monday, matches schedule_blocks.day_of_week

    zoom_link = _zoom_link(user.get("zoom_meeting_id"))
    teacher_name = user.get("teacher_name") or user.get("name") or "Your teacher"
    studio_name = user.get("studio_name")

    results = []
    async for block in db.schedule_blocks.find({"owner_id": owner_id, "day_of_week": weekday}):
        start_h, start_m = block["start_time"].split(":")
        start_dt_ist = datetime.combine(today_ist, datetime.min.time(), tzinfo=IST).replace(
            hour=int(start_h), minute=int(start_m),
        )
        minutes_until = (start_dt_ist - now_ist).total_seconds() / 60
        if abs(minutes_until - REMINDER_MINUTES_BEFORE) > WINDOW_MINUTES / 2:
            continue

        outcome = await _send_block_reminders(owner_id, block, teacher_name, studio_name, zoom_link, today_str)
        results.append({"block_id": str(block["_id"]), "start_time": block["start_time"], **outcome})

    return {"ok": True, "blocks_processed": len(results), "results": results}
