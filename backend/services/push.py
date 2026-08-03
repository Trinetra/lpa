"""Web Push notifications (change-request events). Reads ``VAPID_PUBLIC_KEY``,
``VAPID_PRIVATE_KEY`` and ``VAPID_SUBJECT`` from environment — no-ops (like
services/email.py without RESEND_API_KEY) when they aren't set, so the app
works the same without this configured.
"""

import json
import logging
import os

from pywebpush import WebPushException, webpush

from db import db

logger = logging.getLogger(__name__)


def _vapid_private_key():
    return os.environ.get("VAPID_PRIVATE_KEY")


def _vapid_public_key():
    return os.environ.get("VAPID_PUBLIC_KEY")


def _vapid_claims():
    subject = os.environ.get("VAPID_SUBJECT", "").strip()
    return {"sub": subject if subject.startswith("mailto:") else f"mailto:{subject or 'admin@example.com'}"}


async def send_push(owner_type: str, owner_id: str, title: str, body: str, url: str) -> dict:
    """Push to every subscribed device for this owner (owner_type is 'user'
    for a teacher or 'student'). Expired/revoked subscriptions (404/410) are
    cleaned up automatically; any other failure is logged and skipped rather
    than raised, matching how email sends are swallowed elsewhere."""
    private_key = _vapid_private_key()
    if not private_key or not _vapid_public_key():
        logger.warning(f"Push requested but VAPID keys not set. {owner_type}={owner_id}: {title}")
        return {"sent": 0, "skipped": 0}

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent, skipped = 0, 0
    async for sub in db.push_subscriptions.find({"owner_type": owner_type, "owner_id": owner_id}):
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": sub["keys"],
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims=_vapid_claims(),
            )
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                # The push service says this subscription is gone for good —
                # stop trying it on future notifications.
                await db.push_subscriptions.delete_one({"_id": sub["_id"]})
            else:
                logger.error(f"Push failed for {owner_type} {owner_id}: {e}")
            skipped += 1
        except Exception as e:
            logger.error(f"Push failed for {owner_type} {owner_id}: {e}")
            skipped += 1
    return {"sent": sent, "skipped": skipped}
