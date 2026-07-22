"""Invoice business logic: creation helpers, WhatsApp deep link, date filtering."""

import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

from bson import ObjectId
from pymongo import ReturnDocument

from db import db


async def next_invoice_number(owner_id: str, on_date: datetime, namespace: str = "student") -> str:
    """Atomically allocate the next sequential invoice number for the day, as
    yyyyMMddNN (NN wraps 00-99 — plenty for a single-teacher studio's daily
    volume). Stored on the invoice at creation so it never changes on
    re-render, unlike a number computed fresh from 'now' each time.

    `namespace` keeps separate counters per invoice type (student vs tour)
    so their numbering sequences don't collide/interleave with each other.
    """
    day_key = on_date.strftime("%Y%m%d")
    counter = await db.invoice_counters.find_one_and_update(
        {"_id": f"{owner_id}:{namespace}:{day_key}"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = counter["seq"] % 100
    return f"INV-{day_key}{seq:02d}"


def filter_by_date(items: list, start: Optional[str], end: Optional[str], key: str) -> list:
    out = []
    for it in items:
        d = it.get(key)
        if start and (not d or d < start):
            continue
        if end and (not d or d > end):
            continue
        out.append(it)
    return out


def wa_link(phone: str, message: str) -> str:
    # wa.me needs a full international number. Bare 10-digit Indian numbers
    # (saved before phones were normalized on write) are assumed +91 here too,
    # so existing students don't need to be re-edited for WhatsApp to work.
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) == 10:
        digits = f"91{digits}"
    return f"https://wa.me/{digits}?text={quote(message)}"


def build_studio_snapshot(user_doc: Optional[dict]) -> dict:
    u = user_doc or {}
    return {
        "studio_name": u.get("studio_name"),
        "teacher_name": u.get("teacher_name") or u.get("name"),
        "contact_phone": u.get("contact_phone"),
        "contact_upi": u.get("contact_upi"),
        "contact_email": u.get("contact_email") or u.get("email"),
        "logo_path": u.get("logo_path"),
        "social_youtube": u.get("social_youtube"),
        "social_instagram": u.get("social_instagram"),
        "social_facebook": u.get("social_facebook"),
        "international_payment_details": u.get("international_payment_details"),
    }


async def create_invoice_for_student(owner_id: str, student: dict,
                                      start_date: Optional[str], end_date: Optional[str],
                                      ser_class, ser_payment, ser_student,
                                      user_doc: Optional[dict] = None) -> dict:
    """Create and persist a new invoice document for `student` in the given window.

    Serializer functions are injected to keep this module free of the api-model
    imports in server.py. If `user_doc` is provided the studio snapshot is built
    from it; otherwise it's fetched from mongo.
    """
    student_id = str(student["_id"])
    classes = []
    async for c in db.classes.find({"owner_id": owner_id, "student_id": student_id}).sort("class_date", 1):
        classes.append(ser_class(c))
    payments = []
    async for p in db.payments.find({"owner_id": owner_id, "student_id": student_id}).sort("paid_on", 1):
        payments.append(ser_payment(p))
    classes = filter_by_date(classes, start_date, end_date, "class_date")
    payments = filter_by_date(payments, start_date, end_date, "paid_on")

    total_billed = round(sum(float(c["amount"]) for c in classes), 2)
    total_paid = round(sum(float(p["amount"]) for p in payments), 2)
    summary = {
        "total_billed": total_billed,
        "total_paid": total_paid,
        "balance_due": round(total_billed - total_paid, 2),
    }

    if user_doc is None:
        user_doc = await db.users.find_one({"_id": ObjectId(owner_id)})
    studio_snapshot = build_studio_snapshot(user_doc)

    now = datetime.now(timezone.utc)
    invoice_doc = {
        "invoice_id": str(uuid.uuid4()),
        "invoice_number": await next_invoice_number(owner_id, now),
        "share_token": uuid.uuid4().hex,
        "owner_id": owner_id,
        "student_id": student_id,
        "student_snapshot": ser_student(student),
        "teacher_name": studio_snapshot["teacher_name"] or "Dance Teacher",
        "studio_snapshot": studio_snapshot,
        "classes": classes,
        "payments": payments,
        "summary": summary,
        "start_date": start_date,
        "end_date": end_date,
        "created_at": now.isoformat(),
    }
    await db.invoices.insert_one(invoice_doc)
    return invoice_doc
