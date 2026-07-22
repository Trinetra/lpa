"""Google Calendar sync for weekly training schedule blocks.

One dedicated calendar per (single) teacher account, created automatically
the first time she connects. Each schedule_blocks document gets a matching
recurring (weekly RRULE) event; edits/deletes to the block are mirrored.

Reads GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REDIRECT_URI
from environment. Calendar sync is entirely optional — the schedule works
without it if these are unset or the teacher never connects.
"""

import logging
import os
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleAuthRequest
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from db import db

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.app.created"]
DEFAULT_CALENDAR_NAME = "Lakshmi's Dance Classes"

DAY_RRULE = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def is_configured() -> bool:
    return bool(
        os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
        and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
        and os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    )


def _client_config() -> dict:
    return {
        "web": {
            "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [os.environ["GOOGLE_OAUTH_REDIRECT_URI"]],
        }
    }


def build_auth_url(state: str) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES,
                                    redirect_uri=os.environ["GOOGLE_OAUTH_REDIRECT_URI"])
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force a refresh_token even on repeat connects
        state=state,
    )
    return auth_url


async def handle_oauth_callback(owner_id: str, code: str) -> None:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES,
                                    redirect_uri=os.environ["GOOGLE_OAUTH_REDIRECT_URI"])
    flow.fetch_token(code=code)
    creds = flow.credentials

    user = await db.users.find_one({"_id": owner_id})
    calendar_name = (user or {}).get("google_calendar_name") or DEFAULT_CALENDAR_NAME

    service = build("calendar", "v3", credentials=creds)
    # calendar.app.created only grants access to calendars this app itself
    # creates — it can't list her existing calendars (calendarList().list()
    # needs a broader scope), so each connect creates a fresh one. Disconnect
    # clears our stored google_calendar_id, so there's no duplicate-detection
    # need across reconnects.
    created = service.calendars().insert(body={"summary": calendar_name}).execute()
    calendar_id = created["id"]

    await db.users.update_one(
        {"_id": owner_id},
        {"$set": {
            "google_refresh_token": creds.refresh_token,
            "google_calendar_id": calendar_id,
            "google_calendar_name": calendar_name,
        }},
    )


async def disconnect(owner_id: str) -> None:
    await db.users.update_one(
        {"_id": owner_id},
        {"$unset": {"google_refresh_token": "", "google_calendar_id": ""}},
    )


async def _get_service(owner_id: str):
    user = await db.users.find_one({"_id": owner_id})
    if not user or not user.get("google_refresh_token"):
        return None, None
    creds = Credentials(
        token=None,
        refresh_token=user["google_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        scopes=SCOPES,
    )
    creds.refresh(GoogleAuthRequest())
    service = build("calendar", "v3", credentials=creds)
    return service, user["google_calendar_id"]


def _event_body(block: dict, student_names: list) -> dict:
    # Anchor the first occurrence on the next upcoming instance of that
    # weekday so the RRULE's UNTIL-less weekly recurrence starts "now".
    from datetime import date, timedelta
    today = date.today()
    days_ahead = (block["day_of_week"] - today.weekday()) % 7
    anchor = today + timedelta(days=days_ahead)
    start_h, start_m = block["start_time"].split(":")
    end_h, end_m = block["end_time"].split(":")
    start_dt = f"{anchor.isoformat()}T{start_h}:{start_m}:00"
    end_dt = f"{anchor.isoformat()}T{end_h}:{end_m}:00"

    summary = "Class: " + (", ".join(student_names) if student_names else "Class")
    return {
        "summary": summary,
        "description": block.get("notes") or "",
        "start": {"dateTime": start_dt, "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": end_dt, "timeZone": "Asia/Kolkata"},
        "recurrence": [f"RRULE:FREQ=WEEKLY;BYDAY={DAY_RRULE[block['day_of_week']]}"],
        "reminders": {"useDefault": False, "overrides": [{"method": "email", "minutes": 30}]},
    }


async def sync_block_upsert(owner_id: str, block: dict, student_names: list) -> Optional[str]:
    """Create or update the Google Calendar event for a schedule block.
    Returns the google_event_id, or None if Calendar isn't connected."""
    service, calendar_id = await _get_service(owner_id)
    if not service:
        return None
    body = _event_body(block, student_names)
    try:
        if block.get("google_event_id"):
            event = service.events().update(
                calendarId=calendar_id, eventId=block["google_event_id"], body=body
            ).execute()
        else:
            event = service.events().insert(calendarId=calendar_id, body=body).execute()
        return event["id"]
    except HttpError as e:
        logger.error(f"Calendar sync failed for block: {e}")
        return block.get("google_event_id")


async def sync_block_delete(owner_id: str, google_event_id: Optional[str]) -> None:
    if not google_event_id:
        return
    service, calendar_id = await _get_service(owner_id)
    if not service:
        return
    try:
        service.events().delete(calendarId=calendar_id, eventId=google_event_id).execute()
    except HttpError as e:
        # 410/404 = already gone, fine to ignore.
        if e.resp.status not in (404, 410):
            logger.error(f"Calendar delete failed: {e}")
