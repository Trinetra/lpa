"""Zoom integration: pull the teacher's past meetings so logging a class can
start from "which real session was this" instead of typing everything by
hand.

Uses Server-to-Server OAuth (not the 3-legged consent flow Calendar uses) —
appropriate here because there's exactly one Zoom account involved (the
studio's), not a per-visitor login. Reads ZOOM_ACCOUNT_ID / ZOOM_CLIENT_ID /
ZOOM_CLIENT_SECRET from environment; the integration is entirely optional —
the class log form works without it if these are unset.

Requires a paid Zoom plan (Business/Pro+) for the past-meetings report data;
free-plan accounts will get an authorization error from Zoom on that call.
"""

import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TOKEN_URL = "https://zoom.us/oauth/token"
API_BASE = "https://api.zoom.us/v2"

_cached_token: Optional[str] = None
_cached_token_expiry: float = 0.0


def is_configured() -> bool:
    return bool(
        os.environ.get("ZOOM_ACCOUNT_ID")
        and os.environ.get("ZOOM_CLIENT_ID")
        and os.environ.get("ZOOM_CLIENT_SECRET")
    )


async def _get_access_token() -> str:
    global _cached_token, _cached_token_expiry
    if _cached_token and time.time() < _cached_token_expiry - 60:
        return _cached_token

    account_id = os.environ["ZOOM_ACCOUNT_ID"]
    client_id = os.environ["ZOOM_CLIENT_ID"]
    client_secret = os.environ["ZOOM_CLIENT_SECRET"]

    async with httpx.AsyncClient(timeout=15) as c:
        resp = await c.post(
            TOKEN_URL,
            params={"grant_type": "account_credentials", "account_id": account_id},
            auth=(client_id, client_secret),
        )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = data["access_token"]
    _cached_token_expiry = time.time() + data.get("expires_in", 3600)
    return _cached_token


async def list_past_meetings(from_date: str, to_date: str) -> list:
    """Past meetings for the Zoom account's "me" user in [from_date, to_date]
    (YYYY-MM-DD), newest first. Each item has topic/start_time/duration —
    exactly what's needed to let a teacher pick "which session was this"
    when logging a class. Raises on auth/plan errors rather than swallowing
    them, since a silent empty list would look like "no meetings happened"
    instead of "this isn't set up right"."""
    token = await _get_access_token()
    async with httpx.AsyncClient(timeout=20) as c:
        resp = await c.get(
            f"{API_BASE}/report/users/me/meetings",
            headers={"Authorization": f"Bearer {token}"},
            params={"type": "past", "from": from_date, "to": to_date, "page_size": 100},
        )
    resp.raise_for_status()
    meetings = resp.json().get("meetings", [])
    meetings.sort(key=lambda m: m.get("start_time", ""), reverse=True)
    return [
        {
            "uuid": m.get("uuid"),
            "id": m.get("id"),
            "topic": m.get("topic"),
            "start_time": m.get("start_time"),
            "duration_minutes": m.get("duration"),
        }
        for m in meetings
    ]
