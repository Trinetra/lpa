from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import io
import re
import uuid
import logging
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta, date
from typing import Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import bcrypt
import httpx
import jwt
import requests
import secrets
from collections import defaultdict
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Form, Depends, Query, Header
from fastapi.responses import StreamingResponse, RedirectResponse
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from starlette.middleware.cors import CORSMiddleware

from db import client, db
from services import pdf as pdf_service
from services import email as email_service
from services import invoices as invoices_service
from services import storage as storage_service
from services import calendar as calendar_service
from services import tours as tours_service
from services import backup as backup_service
from services import reminders as reminders_service
from services import zoom as zoom_service
from services import fx as fx_service
from services import push as push_service
from services import geocoding as geocoding_service
from services import transcription as transcription_service

# --------------- Config -----------------
JWT_ALGORITHM = "HS256"
APP_NAME = os.environ.get("APP_NAME", "dance-billing")
# Email-configured flag: true when a Resend key is set. services/email.py
# picks the right transport at call time.
EMAIL_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Pravaaha Center for Movement")
IST = ZoneInfo("Asia/Kolkata")  # schedule_blocks times are entered in IST — all classes are in India.


# Thin wrappers delegating to services.storage, kept so call sites throughout
# this file can use the short names.
def init_storage():
    return storage_service.init()


def put_object(path, data, content_type):
    return storage_service.put_object(path, data, content_type)


def get_object(path):
    return storage_service.get_object(path)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
api_router = APIRouter(prefix="/api")

# --------------- Auth helpers -----------------
def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email,
               "exp": datetime.now(timezone.utc) + timedelta(hours=8),
               "type": "access"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def create_refresh_token(user_id: str) -> str:
    payload = {"sub": user_id,
               "exp": datetime.now(timezone.utc) + timedelta(days=7),
               "type": "refresh"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def set_auth_cookies(response: Response, access: str, refresh: str):
    # SameSite=None + Secure so cookies still work across the frontend (Netlify)
    # and backend (this VPS) being different origins.
    response.set_cookie("access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=8 * 3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=7 * 24 * 3600, path="/")

async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        user["_id"] = str(user["_id"])
        user.pop("password_hash", None)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --------------- Models -----------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class StudentChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class ProfileUpdate(BaseModel):
    studio_name: Optional[str] = None
    teacher_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_upi: Optional[str] = None
    contact_email: Optional[EmailStr] = None
    logo_path: Optional[str] = None
    zoom_meeting_id: Optional[str] = None
    zoom_passcode: Optional[str] = None
    social_youtube: Optional[str] = None
    social_instagram: Optional[str] = None
    social_facebook: Optional[str] = None
    bank_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc_code: Optional[str] = None
    bank_swift_code: Optional[str] = None

SUPPORTED_CURRENCIES = ["INR", "EUR", "USD", "GBP"]
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
CURRENCY_SYMBOLS = {"INR": "₹", "EUR": "€", "USD": "$", "GBP": "£"}
# Browsers pick their own native MediaRecorder codec — Chrome/Firefox/Edge
# default to WebM/Opus, Safari/iOS to MP4/AAC. Both are already compact and
# well-suited for voice; no server-side transcoding needed.
CLASS_AUDIO_CONTENT_TYPES = {"audio/webm", "audio/mp4", "audio/ogg", "audio/mpeg", "audio/wav"}
CLASS_AUDIO_MAX_BYTES = 25 * 1024 * 1024

class StudentCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    level: Optional[str] = None
    joined_on: Optional[str] = None  # ISO date str
    description: Optional[str] = None
    hourly_rate: float = 0.0
    currency: str = "INR"
    photo_path: Optional[str] = None
    expected_inr_amount: Optional[float] = None

class StudentInviteRequest(BaseModel):
    channels: List[str] = Field(default_factory=lambda: ["email"])  # 'email' and/or 'whatsapp'

class OutreachAccessUpdate(BaseModel):
    enabled: bool

class ClassesSuspensionUpdate(BaseModel):
    suspended: bool

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    level: Optional[str] = None
    joined_on: Optional[str] = None
    description: Optional[str] = None
    hourly_rate: Optional[float] = None
    currency: Optional[str] = None
    photo_path: Optional[str] = None
    expected_inr_amount: Optional[float] = None

class ClassLogCreate(BaseModel):
    student_id: str
    hours: float
    class_date: str  # ISO
    notes: Optional[str] = None
    rate_override: Optional[float] = None
    topics: List[str] = Field(default_factory=list)

class ClassLogUpdate(BaseModel):
    hours: Optional[float] = None
    class_date: Optional[str] = None
    notes: Optional[str] = None
    rate_override: Optional[float] = None
    student_id: Optional[str] = None
    topics: Optional[List[str]] = None

class PaymentAllocation(BaseModel):
    class_id: str
    amount: float

class PaymentCreate(BaseModel):
    student_id: str
    amount: float  # in the student's billing currency — what actually clears the debt
    paid_on: str  # ISO
    method: Optional[str] = None
    notes: Optional[str] = None
    # Foreign-currency reconciliation (all optional — a same-currency INR
    # payment just leaves these blank):
    received_amount: Optional[float] = None  # what actually landed in the bank, e.g. INR
    received_currency: Optional[str] = None
    fx_rate: Optional[float] = None  # received_currency -> amount's currency, at recording time
    allocations: List[PaymentAllocation] = Field(default_factory=list)
    # Set from reconcile-preview's meets_inr_target — a foreign-currency
    # payment can fully clear every outstanding class (the student sent
    # enough in their own currency) and still fall short of the INR figure
    # she personally expects to land in her account, if the bank's real
    # conversion rate was worse than what she budgeted for. That never shows
    # up as an outstanding class balance, so it's tracked here instead.
    meets_inr_target: Optional[bool] = None

class InvoiceRequest(BaseModel):
    student_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    include_paid: bool = False

class ScheduleBlockCreate(BaseModel):
    day_of_week: int  # 0=Monday .. 6=Sunday, matches Python's date.weekday()
    start_time: str  # "HH:MM", 24h
    end_time: str    # "HH:MM", 24h
    student_ids: List[str]
    notes: Optional[str] = None
    is_one_off: bool = False  # doesn't repeat — shown once, then auto-removed

class ScheduleBlockUpdate(BaseModel):
    day_of_week: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    student_ids: Optional[List[str]] = None
    notes: Optional[str] = None
    is_one_off: Optional[bool] = None

class CalendarNameUpdate(BaseModel):
    calendar_name: str

class OccurrenceRescheduleRequest(BaseModel):
    date: str  # ISO date, new date for this occurrence
    start_time: str
    end_time: str

class PersonalEventCreate(BaseModel):
    title: str
    date: str  # ISO date
    start_time: str
    end_time: str
    notes: Optional[str] = None

class PersonalEventUpdate(BaseModel):
    title: Optional[str] = None
    date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    notes: Optional[str] = None

EXPENSE_CATEGORIES = ["Flights", "Accommodation", "Local Transport", "Food",
                       "Venue/Equipment", "Other"]

class TourCreate(BaseModel):
    name: str
    start_date: str  # ISO date
    end_date: str
    location: Optional[str] = None
    notes: Optional[str] = None

class TourUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None
    custom_slug: Optional[str] = None

# Top-level app routes a custom tour slug must never collide with (see
# frontend/src/App.js) — the public site resolves an unknown top-level path
# as "try this as a tour slug" only as a fallback, so a slug matching one of
# these would make that whole page unreachable.
RESERVED_SLUGS = {
    "login", "reset-password", "invoice", "tour", "dashboard", "students",
    "schedule", "classes", "payments", "invoices", "tours", "charts", "settings",
    "portal", "requests", "event", "events", "crm", "announcements", "calendar",
    "outreach", "privacy",
}

# Public tour/event links live on the bare root domain, not the app's own
# APP_URL (app.pravaahacfm.com) — see frontend's TourDetailPage/EventDetailPage
# ROOT_DOMAIN constant, which this mirrors for server-built email links.
PUBLIC_ROOT_DOMAIN = "pravaahacfm.com"

class TourStopCreate(BaseModel):
    city: str
    venue: Optional[str] = None
    stop_date: str  # ISO date
    stop_time: Optional[str] = None  # "HH:MM", 24h
    notes: Optional[str] = None

class TourStopUpdate(BaseModel):
    city: Optional[str] = None
    venue: Optional[str] = None
    stop_date: Optional[str] = None
    stop_time: Optional[str] = None
    notes: Optional[str] = None

class TourExpenseCreate(BaseModel):
    category: str
    amount: float
    currency: str = "INR"
    expense_date: str  # ISO date
    notes: Optional[str] = None
    receipt_path: Optional[str] = None

class TourExpenseUpdate(BaseModel):
    category: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    expense_date: Optional[str] = None
    notes: Optional[str] = None
    receipt_path: Optional[str] = None

class TourCheckinCreate(BaseModel):
    latitude: float
    longitude: float
    note: Optional[str] = None

class TourContactCreate(BaseModel):
    name: str
    role: Optional[str] = None  # e.g. "Venue manager", "Promoter"
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None

class TourContactUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = None

class TourFileCreate(BaseModel):
    drive_file_id: str
    name: str
    mime_type: Optional[str] = None
    icon_url: Optional[str] = None
    web_view_link: Optional[str] = None

class TourTodoCreate(BaseModel):
    text: str
    due_date: Optional[str] = None  # ISO date str

class TourTodoUpdate(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None
    due_date: Optional[str] = None

class TourInvoiceCreate(BaseModel):
    contact_id: Optional[str] = None
    recipient_name: str
    recipient_email: Optional[EmailStr] = None
    recipient_phone: Optional[str] = None
    description: str
    invoice_date: str  # ISO date
    amount: float
    currency: str = "INR"

class TourInvoiceUpdate(BaseModel):
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None
    recipient_phone: Optional[str] = None
    description: Optional[str] = None
    invoice_date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    paid: Optional[bool] = None

class TourInvoiceSend(BaseModel):
    channels: List[str] = Field(default_factory=lambda: ["email"])  # 'email' and/or 'whatsapp'

# --------------- Events (workshops) -----------------
class EventCreate(BaseModel):
    name: str
    start_date: str  # ISO date
    end_date: str
    time: Optional[str] = None  # freetext, e.g. "6:00 PM - 8:00 PM IST"
    description: Optional[str] = None
    image_path: Optional[str] = None
    social_instagram: Optional[str] = None
    social_facebook: Optional[str] = None
    price: float = 0.0
    currency: str = "INR"
    zoom_meeting_id: Optional[str] = None
    zoom_passcode: Optional[str] = None

class EventUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    time: Optional[str] = None
    description: Optional[str] = None
    image_path: Optional[str] = None
    social_instagram: Optional[str] = None
    social_facebook: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    zoom_meeting_id: Optional[str] = None
    zoom_passcode: Optional[str] = None
    status: Optional[str] = None  # "draft" | "published"
    custom_slug: Optional[str] = None

EVENT_STATUSES = {"draft", "published"}
EVENT_REGISTRATION_STATUSES = {"pending", "approved", "invited"}
EVENT_PAYMENT_METHODS = {"upi", "bank_transfer"}

class EventRegistrationCreate(BaseModel):
    name: str
    dob: Optional[str] = None  # ISO date
    mobile: str
    email: EmailStr
    city: Optional[str] = None
    country: Optional[str] = None
    experience: Optional[str] = None

class EventRegistrationPayment(BaseModel):
    payment_method: str  # "upi" | "bank_transfer"
    payment_reference: str

class EventRegistrationApprove(BaseModel):
    payment_amount: Optional[float] = None
    payment_notes: Optional[str] = None

class EventPushInviteRequest(BaseModel):
    registration_ids: Optional[List[str]] = None  # None => all approved-not-yet-invited

class CrmBulkInviteRequest(BaseModel):
    contact_ids: List[str]
    event_id: str

class AnnouncementCreate(BaseModel):
    body: str
    image_path: Optional[str] = None

class AnnouncementUpdate(BaseModel):
    body: Optional[str] = None
    image_path: Optional[str] = None
    force: bool = False  # re-send to contacts already invited to this event

class OutreachTemplateCreate(BaseModel):
    name: str
    subject: str
    html: str
    default_values: Dict[str, str] = Field(default_factory=dict)

class OutreachTemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    html: Optional[str] = None
    default_values: Optional[Dict[str, str]] = None

class OutreachSendRequest(BaseModel):
    to_email: EmailStr
    reply_to: Optional[EmailStr] = None
    field_values: Dict[str, str] = Field(default_factory=dict)

# --------------- Serializers -----------------
def ser_student(doc):
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "level": doc.get("level"),
        "joined_on": doc.get("joined_on"),
        "description": doc.get("description"),
        "hourly_rate": doc.get("hourly_rate", 0.0),
        "currency": doc.get("currency", "INR"),
        "photo_path": doc.get("photo_path"),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at"),
        "portal_active": bool(doc.get("password_hash")),
        "outreach_access": doc.get("outreach_access", False),
        "expected_inr_amount": doc.get("expected_inr_amount"),
    }

def ser_class(doc):
    return {
        "id": str(doc["_id"]),
        "student_id": doc.get("student_id"),
        "hours": doc.get("hours"),
        "class_date": doc.get("class_date"),
        "notes": doc.get("notes"),
        "topics": doc.get("topics", []),
        "rate": doc.get("rate"),
        "currency": doc.get("currency", "INR"),
        "amount": doc.get("amount"),
        "created_at": doc.get("created_at"),
        "has_audio": bool(doc.get("audio_path")),
        "audio_duration_seconds": doc.get("audio_duration_seconds"),
        "transcript": doc.get("transcript"),
        "transcript_status": doc.get("transcript_status"),
    }

def ser_payment(doc):
    return {
        "id": str(doc["_id"]),
        "student_id": doc.get("student_id"),
        "amount": doc.get("amount"),
        "paid_on": doc.get("paid_on"),
        "method": doc.get("method"),
        "notes": doc.get("notes"),
        "received_amount": doc.get("received_amount"),
        "received_currency": doc.get("received_currency"),
        "fx_rate": doc.get("fx_rate"),
        "meets_inr_target": doc.get("meets_inr_target"),
        "allocations": doc.get("allocations", []),
        "created_at": doc.get("created_at"),
    }

def ser_schedule_block(doc):
    return {
        "id": str(doc["_id"]),
        "day_of_week": doc.get("day_of_week"),
        "start_time": doc.get("start_time"),
        "end_time": doc.get("end_time"),
        "student_ids": doc.get("student_ids", []),
        "notes": doc.get("notes"),
        "is_one_off": doc.get("is_one_off", False),
        "created_at": doc.get("created_at"),
        "synced_to_calendar": bool(doc.get("google_event_id")),
    }

def ser_occurrence(doc):
    return {
        "id": str(doc["_id"]),
        "block_id": doc.get("block_id"),
        "date": doc.get("date"),
        "start_time": doc.get("start_time"),
        "end_time": doc.get("end_time"),
        "student_ids": doc.get("student_ids", []),
        "notes": doc.get("notes"),
        "status": doc.get("status", "scheduled"),
        "origin": doc.get("origin", "recurring"),
        "moved_from_date": doc.get("moved_from_date"),
        "moved_from_start_time": doc.get("moved_from_start_time"),
        "moved_from_end_time": doc.get("moved_from_end_time"),
    }

def ser_occurrence_for_student(doc):
    # Deliberately omits student_ids — a student must never learn who else is
    # on a shared occurrence.
    return {
        "id": str(doc["_id"]),
        "date": doc.get("date"),
        "start_time": doc.get("start_time"),
        "end_time": doc.get("end_time"),
        "notes": doc.get("notes"),
        "status": doc.get("status", "scheduled"),
        "origin": doc.get("origin", "recurring"),
    }

def ser_personal_event(doc):
    return {
        "id": str(doc["_id"]),
        "title": doc.get("title"),
        "date": doc.get("date"),
        "start_time": doc.get("start_time"),
        "end_time": doc.get("end_time"),
        "notes": doc.get("notes"),
        "created_at": doc.get("created_at"),
    }

def ser_tour(doc):
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "start_date": doc.get("start_date"),
        "end_date": doc.get("end_date"),
        "location": doc.get("location"),
        "notes": doc.get("notes"),
        "share_token": doc.get("share_token"),
        "custom_slug": doc.get("custom_slug"),
        "created_at": doc.get("created_at"),
    }

def ser_event(doc):
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "start_date": doc.get("start_date"),
        "end_date": doc.get("end_date"),
        "time": doc.get("time"),
        "description": doc.get("description"),
        "image_path": doc.get("image_path"),
        "social_instagram": doc.get("social_instagram"),
        "social_facebook": doc.get("social_facebook"),
        "price": doc.get("price", 0.0),
        "currency": doc.get("currency", "INR"),
        "zoom_meeting_id": doc.get("zoom_meeting_id"),
        "zoom_passcode": doc.get("zoom_passcode"),
        "status": doc.get("status", "draft"),
        "share_token": doc.get("share_token"),
        "custom_slug": doc.get("custom_slug"),
        "created_at": doc.get("created_at"),
    }

def ser_event_registration(doc):
    return {
        "id": str(doc["_id"]),
        "event_id": doc.get("event_id"),
        "name": doc.get("name"),
        "dob": doc.get("dob"),
        "mobile": doc.get("mobile"),
        "email": doc.get("email"),
        "city": doc.get("city"),
        "country": doc.get("country"),
        "experience": doc.get("experience"),
        "status": doc.get("status", "pending"),
        "payment_method": doc.get("payment_method"),
        "payment_reference": doc.get("payment_reference"),
        "payment_proof_path": doc.get("payment_proof_path"),
        "payment_amount": doc.get("payment_amount"),
        "payment_notes": doc.get("payment_notes"),
        "created_at": doc.get("created_at"),
        "approved_at": doc.get("approved_at"),
        "invited_at": doc.get("invited_at"),
    }

def ser_crm_contact(doc):
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "email": doc.get("email"),
        "mobile": doc.get("mobile"),
        "city": doc.get("city"),
        "country": doc.get("country"),
        "dob": doc.get("dob"),
        "created_at": doc.get("created_at"),
    }

def ser_announcement(doc):
    return {
        "id": str(doc["_id"]),
        "body": doc.get("body"),
        "image_path": doc.get("image_path"),
        "is_retracted": doc.get("is_retracted", False),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

# Matches {{Field Name}} tokens in a template's raw HTML — the set of
# distinct names found is what drives the fill-in form on the frontend, so
# adding a new {{...}} token to a template's HTML is enough to add a new
# field, no code change needed.
#
# A token prefixed "para:" (e.g. {{para:Intro}}) is a rich-text region — her
# fill-in value is HTML produced by the outreach editor's contenteditable
# toolbar, sanitized through _sanitize_rich_html before it's ever stored or
# merged in. This is the only way free text from her ever reaches an
# outreach email: every tag and style property is checked against a fixed
# allowlist and every color/size/alignment choice is re-emitted as an
# explicit inline style, so nothing she types can produce markup Gmail's
# sanitizer might mangle differently than the rest of the template (the
# same failure mode that broke this template once already — see the
# earlier text-align/font-family fix). A bare token with no prefix stays a
# plain inline word-for-word substitution. A token prefixed "bg:" is a page
# background color swatch — only ever used inside a fixed
# style="background-color: {{bg:Name}};" the template itself already
# authored, so it's rendered with a strict #rrggbb check rather than the
# general escape used for free text.
_MERGE_FIELD_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
PARAGRAPH_FIELD_PREFIX = "para:"
BACKGROUND_FIELD_PREFIX = "bg:"
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

def _merge_fields_in(html: str) -> List[dict]:
    seen = []
    names = []
    for m in _MERGE_FIELD_RE.finditer(html):
        raw = m.group(1)
        if raw in names:
            continue
        names.append(raw)
        if raw.startswith(PARAGRAPH_FIELD_PREFIX):
            seen.append({"token": raw, "name": raw[len(PARAGRAPH_FIELD_PREFIX):].strip(), "kind": "paragraph"})
        elif raw.startswith(BACKGROUND_FIELD_PREFIX):
            seen.append({"token": raw, "name": raw[len(BACKGROUND_FIELD_PREFIX):].strip(), "kind": "color"})
        else:
            seen.append({"token": raw, "name": raw, "kind": "text"})
    return seen

def _escape_html(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

# --------------- Rich-text sanitizer (outreach editable regions) -----------------
# Allowlist-based: anything not explicitly permitted is dropped (tag stripped
# but its text/children kept; disallowed attributes/style properties simply
# omitted). This is deliberately narrow — exactly the formatting the
# outreach editor's toolbar can produce (bold/italic/underline, color, font
# size, alignment, links, images) — not a general HTML sanitizer.
_RICH_ALLOWED_TAGS = {"p", "span", "strong", "em", "u", "a", "img", "br"}
_RICH_ALLOWED_STYLE_PROPS = {"color", "font-size", "font-weight", "font-style", "text-decoration", "text-align"}
_RICH_VOID_TAGS = {"br", "img"}
_RICH_BASE_FONT = "font-family:Georgia,'Times New Roman',serif;"
# Browsers' execCommand("bold"/"italic") produce legacy <b>/<i> (Chrome,
# Edge) rather than <strong>/<em> — normalized here so formatting from the
# outreach editor's toolbar survives the allowlist instead of silently
# vanishing (looked applied in the editor, disappeared in the preview/send).
_RICH_TAG_ALIASES = {"b": "strong", "i": "em"}

def _sanitize_style_attr(style: str) -> str:
    out = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        prop, _, val = decl.partition(":")
        prop = prop.strip().lower()
        val = val.strip()
        if prop in _RICH_ALLOWED_STYLE_PROPS and val and "expression(" not in val.lower() and "javascript:" not in val.lower():
            out.append(f"{prop}:{val}")
    return "; ".join(out)

def _sanitize_url(url: str) -> str:
    url = url.strip()
    if url.lower().startswith(("http://", "https://", "mailto:")):
        return url
    return ""

class _RichHtmlSanitizer(HTMLParser):
    """Allowlist HTML -> HTML sanitizer with an explicit open-tag stack, so
    output can never contain more closing tags than opening ones — a
    malformed or adversarial input can't emit a stray </p> (or similar)
    that closes something outside this fragment once it's spliced into the
    template via string substitution."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.open_stack = []  # tag names currently open, in the OUTPUT

    def handle_starttag(self, tag, attrs):
        self._emit(_RICH_TAG_ALIASES.get(tag, tag), attrs)

    def handle_startendtag(self, tag, attrs):
        self._emit(_RICH_TAG_ALIASES.get(tag, tag), attrs, force_void=True)

    def _emit(self, tag, attrs, force_void=False):
        if tag not in _RICH_ALLOWED_TAGS:
            return
        attr_map = dict(attrs)
        kept = []
        style = _sanitize_style_attr(attr_map.get("style", ""))
        if tag == "p":
            base = f"margin:0 0 16px 0; text-align:left; {_RICH_BASE_FONT} font-size:16px; line-height:1.65; color:#3a3a3a;"
            style = f"{base} {style}".strip()
        elif tag == "span" and not style:
            return  # an empty formatting span carries nothing worth keeping
        if style:
            kept.append(f'style="{style}"')
        if tag == "a":
            href = _sanitize_url(attr_map.get("href", ""))
            if not href:
                tag = "span"  # a link with no safe href is just its text
                if not style:
                    return
            else:
                kept.append(f'href="{href}"')
                kept.append('target="_blank"')
        if tag == "img":
            src = _sanitize_url(attr_map.get("src", ""))
            if not src:
                return
            kept.append(f'src="{src}"')
            for a in ("width", "height", "alt"):
                if attr_map.get(a):
                    safe = _escape_html(str(attr_map[a]))
                    kept.append(f'{a}="{safe}"')
        is_void = force_void or tag in _RICH_VOID_TAGS
        tag_str = f"<{tag}" + ("".join(" " + k for k in kept)) + (" />" if is_void else ">")
        self.out.append(tag_str)
        if not is_void:
            self.open_stack.append(tag)

    def handle_endtag(self, tag):
        # Only close what's actually open, and only the innermost matching
        # tag — anything more (extra closes, closing something never
        # opened, closing out of order) is silently dropped rather than
        # trusted from the input.
        tag = _RICH_TAG_ALIASES.get(tag, tag)
        if tag in self.open_stack:
            while self.open_stack:
                top = self.open_stack.pop()
                self.out.append(f"</{top}>")
                if top == tag:
                    break

    def handle_data(self, data):
        self.out.append(_escape_html(data))

    def close(self):
        super().close()
        while self.open_stack:
            self.out.append(f"</{self.open_stack.pop()}>")

def _sanitize_rich_html(raw_html: str) -> str:
    parser = _RichHtmlSanitizer()
    parser.feed(raw_html or "")
    parser.close()
    return "".join(parser.out)

def _merge_outreach_html(html: str, field_values: Dict[str, str]) -> str:
    for field in _merge_fields_in(html):
        value = field_values.get(field["name"], "")
        token_str = "{{" + field["token"] + "}}"
        if field["kind"] == "paragraph":
            html = html.replace(token_str, _sanitize_rich_html(value))
        elif field["kind"] == "color":
            html = html.replace(token_str, value if _HEX_COLOR_RE.match(value or "") else "#ffffff")
        else:
            html = html.replace(token_str, _escape_html(value))
    return html

def ser_outreach_template(doc):
    return {
        "id": str(doc["_id"]),
        "name": doc.get("name"),
        "subject": doc.get("subject"),
        "html": doc.get("html"),
        "merge_fields": _merge_fields_in(doc.get("html", "")),
        "default_values": doc.get("default_values", {}),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

def ser_tour_stop(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "city": doc.get("city"),
        "venue": doc.get("venue"),
        "stop_date": doc.get("stop_date"),
        "stop_time": doc.get("stop_time"),
        "notes": doc.get("notes"),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "formatted_address": doc.get("formatted_address"),
        "created_at": doc.get("created_at"),
    }

def ser_tour_expense(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "category": doc.get("category"),
        "amount": doc.get("amount"),
        "currency": doc.get("currency", "INR"),
        "expense_date": doc.get("expense_date"),
        "notes": doc.get("notes"),
        "receipt_path": doc.get("receipt_path"),
        "created_at": doc.get("created_at"),
    }

def ser_tour_checkin(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "note": doc.get("note"),
        "created_at": doc.get("created_at"),
    }

def ser_tour_contact(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "name": doc.get("name"),
        "role": doc.get("role"),
        "phone": doc.get("phone"),
        "email": doc.get("email"),
        "notes": doc.get("notes"),
        "created_at": doc.get("created_at"),
    }

def ser_tour_file(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "drive_file_id": doc.get("drive_file_id"),
        "name": doc.get("name"),
        "mime_type": doc.get("mime_type"),
        "icon_url": doc.get("icon_url"),
        "web_view_link": doc.get("web_view_link"),
        "created_at": doc.get("created_at"),
    }

def ser_tour_todo(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "text": doc.get("text"),
        "done": doc.get("done", False),
        "due_date": doc.get("due_date"),
        "created_at": doc.get("created_at"),
    }

def ser_tour_invoice(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "contact_id": doc.get("contact_id"),
        "invoice_number": doc.get("invoice_number"),
        "recipient_name": doc.get("recipient_name"),
        "recipient_email": doc.get("recipient_email"),
        "recipient_phone": doc.get("recipient_phone"),
        "description": doc.get("description"),
        "invoice_date": doc.get("invoice_date"),
        "amount": doc.get("amount"),
        "currency": doc.get("currency"),
        "paid": doc.get("paid", False),
        "share_token": doc.get("share_token"),
        "last_sent_to": doc.get("last_sent_to"),
        "last_sent_at": doc.get("last_sent_at"),
        "created_at": doc.get("created_at"),
    }

# --------------- Auth endpoints -----------------
@api_router.post("/auth/login")
async def login(body: LoginRequest, response: Response):
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    uid = str(user["_id"])
    access = create_access_token(uid, email)
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    return {"id": uid, "email": email, "name": user.get("name"), "token": access}

@api_router.post("/auth/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    # Must match the attributes used in set_auth_cookies() — browsers can
    # silently ignore a Set-Cookie deletion whose SameSite/Secure don't match
    # the cookie actually stored, leaving the session cookie alive.
    response.delete_cookie("access_token", path="/", secure=True, samesite="none")
    response.delete_cookie("refresh_token", path="/", secure=True, samesite="none")
    return {"ok": True}

@api_router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user["_id"], "email": user.get("email"), "name": user.get("name")}

@api_router.post("/auth/refresh")
async def refresh(request: Request, response: Response):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        access = create_access_token(str(user["_id"]), user["email"])
        response.set_cookie("access_token", access, httponly=True, secure=True,
                            samesite="none", max_age=8 * 3600, path="/")
        return {"ok": True}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@api_router.post("/auth/change-password")
async def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    if not full or not verify_password(body.current_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await db.users.update_one(
        {"_id": ObjectId(user["_id"])},
        {"$set": {"password_hash": hash_password(body.new_password)}}
    )
    return {"ok": True}

async def _send_password_reset_email(to_email: str, name: str, reset_link: str):
    await email_service.send_password_reset_email(to_email, name, reset_link)

@api_router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Shared by both the teacher login and the student portal login — looks
    up a teacher account first, then falls back to student accounts (a
    student's email may not be unique across studios, so every match gets its
    own token/email). Always returns the same generic response either way."""
    email = body.email.lower().strip()
    app_url = os.environ.get("APP_URL", "").rstrip("/")
    user = await db.users.find_one({"email": email})
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "account_type": "user",
            "user_id": str(user["_id"]),
            "email": email,
            "used": False,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        })
        reset_link = f"{app_url}/reset-password?token={token}"
        logger.info(f"Password reset link for {email}: {reset_link}")
        await _send_password_reset_email(email, user.get("name") or "", reset_link)
    else:
        async for student in db.students.find({"email": email, "is_active": {"$ne": False}}):
            token = secrets.token_urlsafe(32)
            await db.password_reset_tokens.insert_one({
                "token": token,
                "account_type": "student",
                "student_id": str(student["_id"]),
                "owner_id": student["owner_id"],
                "email": email,
                "used": False,
                "created_at": datetime.now(timezone.utc),
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            })
            reset_link = f"{app_url}/reset-password?token={token}"
            logger.info(f"Student password reset link for {email}: {reset_link}")
            await _send_password_reset_email(email, student.get("name") or "", reset_link)
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}

@api_router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordRequest):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    rec = await db.password_reset_tokens.find_one({"token": body.token})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    if rec.get("used"):
        raise HTTPException(status_code=400, detail="Reset link already used")
    expires_at = rec.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not expires_at or expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset link has expired")

    account_type = rec.get("account_type", "user")
    if account_type == "student":
        await db.students.update_one(
            {"_id": ObjectId(rec["student_id"])},
            {"$set": {"password_hash": hash_password(body.new_password)}}
        )
    else:
        await db.users.update_one(
            {"_id": ObjectId(rec["user_id"])},
            {"$set": {"password_hash": hash_password(body.new_password)}}
        )
    await db.password_reset_tokens.update_one(
        {"_id": rec["_id"]}, {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}}
    )
    return {"ok": True, "account_type": account_type}

# --------------- Profile endpoints -----------------
def _ser_profile(user_doc: dict) -> dict:
    return {
        "id": str(user_doc["_id"]),
        "email": user_doc.get("email"),
        "name": user_doc.get("name"),
        "studio_name": user_doc.get("studio_name"),
        "teacher_name": user_doc.get("teacher_name") or user_doc.get("name"),
        "contact_phone": user_doc.get("contact_phone"),
        "contact_upi": user_doc.get("contact_upi"),
        "contact_email": user_doc.get("contact_email") or user_doc.get("email"),
        "logo_path": user_doc.get("logo_path"),
        "zoom_meeting_id": user_doc.get("zoom_meeting_id"),
        "zoom_passcode": user_doc.get("zoom_passcode"),
        "social_youtube": user_doc.get("social_youtube"),
        "social_instagram": user_doc.get("social_instagram"),
        "social_facebook": user_doc.get("social_facebook"),
        "bank_name": user_doc.get("bank_name"),
        "bank_account_number": user_doc.get("bank_account_number"),
        "bank_ifsc_code": user_doc.get("bank_ifsc_code"),
        "bank_swift_code": user_doc.get("bank_swift_code"),
        "classes_suspended": user_doc.get("classes_suspended", False),
        "classes_suspended_at": user_doc.get("classes_suspended_at"),
    }

@api_router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)):
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    return _ser_profile(full)

@api_router.patch("/profile")
async def update_profile(body: ProfileUpdate, user: dict = Depends(get_current_user)):
    # Convert empty strings to None so the UI can clear fields (e.g. Remove logo).
    raw = body.model_dump(exclude_unset=True)
    updates = {k: (None if isinstance(v, str) and v == "" else v) for k, v in raw.items()}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.users.update_one({"_id": ObjectId(user["_id"])}, {"$set": updates})
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    return _ser_profile(full)

@api_router.post("/classes-suspension")
async def set_classes_suspension(body: ClassesSuspensionUpdate, user: dict = Depends(get_current_user)):
    """A temporary, whole-studio pause — e.g. while Lakshmi is travelling.
    While suspended: the 30-min-before class reminder cron no-ops entirely
    (see reminders.send_due_reminders), and every student's schedule/
    calendar view and reschedule-request flow show a "classes are paused"
    state instead of their normal data. Nothing is deleted — schedule_blocks
    and class_occurrences are untouched, so resuming just picks back up
    exactly where things left off."""
    updates = {"classes_suspended": body.suspended}
    updates["classes_suspended_at"] = datetime.now(timezone.utc).isoformat() if body.suspended else None
    await db.users.update_one({"_id": ObjectId(user["_id"])}, {"$set": updates})
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    return _ser_profile(full)

# --------------- Upload endpoint -----------------
@api_router.post("/uploads/photo")
async def upload_photo(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads allowed")
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    path = f"{APP_NAME}/uploads/{user['_id']}/{uuid.uuid4()}.{ext}"
    data = await file.read()
    result = put_object(path, data, file.content_type)
    await db.files.insert_one({
        "storage_path": result["path"],
        "user_id": user["_id"],
        "content_type": file.content_type,
        "size": result.get("size"),
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    return {"path": result["path"]}

@api_router.get("/uploads/file")
async def get_file(path: str = Query(...), auth: Optional[str] = Query(None), request: Request = None):
    # Auth: cookie, ?auth=<token>, or Authorization: Bearer <token>
    token = request.cookies.get("access_token") if request else None
    if not token and auth:
        token = auth
    if not token and request is not None:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    record = await db.files.find_one({"storage_path": path, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="Not found")
    data, ct = get_object(path)
    return Response(content=data, media_type=record.get("content_type", ct))

# --------------- Students endpoints -----------------
def _normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Add the +91 country code to bare 10-digit Indian mobile numbers.

    wa.me links need a full international number to resolve — a phone saved
    as e.g. "9884430099" silently fails to open in WhatsApp otherwise. Numbers
    that already carry a country code (start with '+', or '91' for an
    11-12 digit number) are left untouched.
    """
    if not phone:
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if phone.strip().startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+91{digits}"
    return phone

@api_router.get("/students")
async def list_students(user: dict = Depends(get_current_user)):
    cur = db.students.find({"owner_id": user["_id"]}).sort("created_at", -1)
    out = []
    async for d in cur:
        out.append(ser_student(d))
    return out

@api_router.post("/students")
async def create_student(body: StudentCreate, user: dict = Depends(get_current_user)):
    if body.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    doc = body.model_dump()
    doc["phone"] = _normalize_phone(doc.get("phone"))
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.students.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_student(doc)

@api_router.get("/students/{sid}")
async def get_student(sid: str, user: dict = Depends(get_current_user)):
    doc = await db.students.find_one({"_id": ObjectId(sid), "owner_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found")
    return ser_student(doc)

@api_router.patch("/students/{sid}")
async def update_student(sid: str, body: StudentUpdate, user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "currency" in updates and updates["currency"] not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    if "phone" in updates:
        updates["phone"] = _normalize_phone(updates["phone"])
    res = await db.students.update_one(
        {"_id": ObjectId(sid), "owner_id": user["_id"]}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    doc = await db.students.find_one({"_id": ObjectId(sid)})
    return ser_student(doc)

@api_router.delete("/students/{sid}")
async def delete_student(sid: str, user: dict = Depends(get_current_user)):
    res = await db.students.delete_one({"_id": ObjectId(sid), "owner_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    # cascade delete classes/payments
    await db.classes.delete_many({"student_id": sid, "owner_id": user["_id"]})
    await db.payments.delete_many({"student_id": sid, "owner_id": user["_id"]})
    return {"ok": True}

@api_router.post("/students/{sid}/deactivate")
async def deactivate_student(sid: str, user: dict = Depends(get_current_user)):
    doc = await db.students.find_one({"_id": ObjectId(sid), "owner_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Student not found")
    await db.students.update_one({"_id": ObjectId(sid)}, {"$set": {"is_active": False}})

    # A deactivated student shouldn't keep occupying a slot on the weekly
    # schedule (or its synced Calendar event) — pull them out of every block,
    # removing the block entirely if they were its only student.
    async for block in db.schedule_blocks.find({"owner_id": user["_id"], "student_ids": sid}):
        remaining = [s for s in block["student_ids"] if s != sid]
        if remaining:
            await db.schedule_blocks.update_one({"_id": block["_id"]}, {"$set": {"student_ids": remaining}})
            names = await _student_names(user["_id"], remaining)
            updated = await db.schedule_blocks.find_one({"_id": block["_id"]})
            event_id = await calendar_service.sync_block_upsert(user["_id"], updated, names)
            if event_id and event_id != updated.get("google_event_id"):
                await db.schedule_blocks.update_one({"_id": block["_id"]}, {"$set": {"google_event_id": event_id}})
        else:
            await calendar_service.sync_block_delete(user["_id"], block.get("google_event_id"))
            await db.schedule_blocks.delete_one({"_id": block["_id"]})

    return ser_student(await db.students.find_one({"_id": ObjectId(sid)}))

@api_router.post("/students/{sid}/reactivate")
async def reactivate_student(sid: str, user: dict = Depends(get_current_user)):
    res = await db.students.update_one(
        {"_id": ObjectId(sid), "owner_id": user["_id"]}, {"$set": {"is_active": True}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    return ser_student(await db.students.find_one({"_id": ObjectId(sid)}))

@api_router.post("/students/{sid}/outreach-access")
async def set_student_outreach_access(sid: str, body: OutreachAccessUpdate, user: dict = Depends(get_current_user)):
    """Grants or revokes this student's access to the Outreach module — she
    can then send cold-outreach emails on Lakshmi's behalf using Lakshmi's
    saved templates, same as Lakshmi herself, minus deleting templates."""
    res = await db.students.update_one(
        {"_id": ObjectId(sid), "owner_id": user["_id"]}, {"$set": {"outreach_access": body.enabled}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Student not found")
    return ser_student(await db.students.find_one({"_id": ObjectId(sid)}))

@api_router.post("/students/{sid}/send-portal-invite")
async def send_student_portal_invite(sid: str, body: StudentInviteRequest, user: dict = Depends(get_current_user)):
    student = await db.students.find_one({"_id": ObjectId(sid), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    if not body.channels:
        raise HTTPException(status_code=400, detail="At least one channel is required")
    channels = set(body.channels)
    if not channels.issubset({"email", "whatsapp"}):
        raise HTTPException(status_code=400, detail="Unknown channel")

    # A fresh invite supersedes any earlier unused one for this student, so
    # there's never more than one live invite link floating around.
    await db.student_invites.update_many(
        {"student_id": sid, "used": False},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
    )
    token = secrets.token_urlsafe(32)
    await db.student_invites.insert_one({
        "token": token,
        "student_id": sid,
        "owner_id": user["_id"],
        "used": False,
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    })

    app_url = (os.environ.get("APP_URL") or "").rstrip("/")
    invite_link = f"{app_url}/portal/accept-invite?token={token}"
    # The studio brand, not the teacher's personal name — matches how the
    # class-reminder email already picks its "brand" (services/reminders.py).
    teacher_name = user.get("studio_name") or user.get("teacher_name") or user.get("name") or "your teacher"

    result = {}

    if "email" in channels:
        if not student.get("email"):
            result["email"] = {"status": "skipped", "reason": "no email on file"}
        elif not EMAIL_KEY:
            result["email"] = {"status": "skipped", "reason": "email not configured"}
        else:
            try:
                await email_service.send_student_invite_email(
                    student["email"], student.get("name") or "", teacher_name, invite_link,
                )
                result["email"] = {"status": "sent", "to": student["email"]}
            except Exception as e:
                logger.error(f"Portal invite email failed for {sid}: {e}")
                result["email"] = {"status": "error", "detail": "email dispatch failed"}

    if "whatsapp" in channels:
        if not student.get("phone"):
            result["whatsapp"] = {"status": "skipped", "reason": "no phone on file"}
        else:
            msg = (f"Hi {student.get('name') or ''}, {teacher_name} has set up a student portal for you. "
                   f"Tap this link to sign in and set your password:\n{invite_link}")
            result["whatsapp"] = {"status": "ready", "url": _wa_link(student["phone"], msg)}

    return {"channels": result}

# --------------- Classes endpoints -----------------
@api_router.get("/classes")
async def list_classes(student_id: Optional[str] = None, limit: int = 500,
                        user: dict = Depends(get_current_user)):
    q = {"owner_id": user["_id"]}
    if student_id:
        q["student_id"] = student_id
    cur = db.classes.find(q).sort("class_date", -1).limit(limit)
    out = []
    async for d in cur:
        out.append(ser_class(d))
    return out

async def _remember_topics(owner_id: str, topics: List[str]):
    """Add any not-yet-seen topics to the studio-wide autocomplete list, so
    typing "Alarippu" once makes it suggestible for every student/teacher
    afterwards. Silently no-ops for blank/whitespace-only entries."""
    for t in topics:
        name = t.strip()
        if not name:
            continue
        await db.class_topics.update_one(
            {"owner_id": owner_id, "name": name},
            {"$setOnInsert": {"owner_id": owner_id, "name": name,
                               "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

@api_router.get("/class-topics")
async def list_class_topics(user: dict = Depends(get_current_user)):
    cur = db.class_topics.find({"owner_id": user["_id"]}).sort("name", 1)
    return [t["name"] async for t in cur]

@api_router.delete("/class-topics")
async def delete_class_topic(name: str = Query(...), user: dict = Depends(get_current_user)):
    # A query param, not a path segment — topic names can contain "/" (dance
    # notation sometimes does), which Starlette's router won't reliably
    # accept even URL-encoded in a path.
    #
    # Removes it from the autocomplete dictionary only — classes that
    # already have this topic logged keep it untouched, same as deleting a
    # tag from a taxonomy doesn't rewrite past records.
    res = await db.class_topics.delete_one({"owner_id": user["_id"], "name": name})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"ok": True}

@api_router.get("/zoom/status")
async def zoom_status(user: dict = Depends(get_current_user)):
    return {"configured": zoom_service.is_configured()}

@api_router.get("/zoom/past-meetings")
async def zoom_past_meetings(days: int = 14, user: dict = Depends(get_current_user)):
    """Past Zoom sessions from the last `days` days, for the "pick which
    session this was" step when logging a class. 404s (not 200-with-empty)
    when Zoom isn't connected, so the frontend can tell "nothing to show"
    apart from "this isn't set up"."""
    if not zoom_service.is_configured():
        raise HTTPException(status_code=404, detail="Zoom not connected")
    from datetime import date as _date, timedelta as _timedelta
    today_d = _date.today()
    from_date = (today_d - _timedelta(days=days)).isoformat()
    to_date = today_d.isoformat()
    try:
        return await zoom_service.list_past_meetings(from_date, to_date)
    except Exception as e:
        logger.error(f"Zoom past-meetings fetch failed: {e}")
        raise HTTPException(status_code=502, detail="Could not reach Zoom — check the connection in Settings")

@api_router.post("/classes")
async def create_class(body: ClassLogCreate, user: dict = Depends(get_current_user)):
    student = await db.students.find_one(
        {"_id": ObjectId(body.student_id), "owner_id": user["_id"]}
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    rate = body.rate_override if body.rate_override is not None else student.get("hourly_rate", 0.0)
    topics = [t.strip() for t in body.topics if t.strip()]
    doc = {
        "owner_id": user["_id"],
        "student_id": body.student_id,
        "hours": body.hours,
        "class_date": body.class_date,
        "notes": body.notes,
        "topics": topics,
        "rate": rate,
        # Snapshotted from the student at creation time — if her billing
        # currency changes later, past classes stay denominated in whatever
        # they were actually billed in.
        "currency": student.get("currency", "INR"),
        "amount": round(body.hours * rate, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.classes.insert_one(doc)
    doc["_id"] = res.inserted_id
    if topics:
        await _remember_topics(user["_id"], topics)
    return ser_class(doc)

@api_router.delete("/classes/{cid}")
async def delete_class(cid: str, user: dict = Depends(get_current_user)):
    res = await db.classes.delete_one({"_id": ObjectId(cid), "owner_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Class not found")
    return {"ok": True}

@api_router.patch("/classes/{cid}")
async def update_class(cid: str, body: ClassLogUpdate, user: dict = Depends(get_current_user)):
    existing = await db.classes.find_one({"_id": ObjectId(cid), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Class not found")

    # exclude_unset (not "v is not None") so a field explicitly cleared to
    # null/empty-string in the request — e.g. clearing the Notes field —
    # actually gets saved as cleared, instead of being silently dropped
    # because it looks the same as "field not included in this PATCH".
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Resolve student for rate calc
    student_id = updates.get("student_id", existing["student_id"])
    student = await db.students.find_one({"_id": ObjectId(student_id), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    hours = updates.get("hours", existing.get("hours"))
    # rate_override key present in the request -> use it (including an
    # explicit null, meaning "clear the override, fall back to the
    # student's rate" — see the branch below).
    if "rate_override" in updates and updates["rate_override"] is not None:
        rate = updates["rate_override"]
    elif "rate_override" not in updates and existing.get("rate") is not None and existing.get("student_id") == student_id and updates.get("student_id") is None:
        # keep existing rate if student unchanged and no override change
        rate = existing.get("rate")
    else:
        rate = student.get("hourly_rate", 0.0)
    updates["rate"] = rate
    updates["amount"] = round(float(hours) * float(rate), 2)
    if updates.get("student_id"):
        updates["currency"] = student.get("currency", "INR")

    if "topics" in updates:
        updates["topics"] = [t.strip() for t in updates["topics"] if t.strip()]

    await db.classes.update_one({"_id": ObjectId(cid)}, {"$set": updates})
    doc = await db.classes.find_one({"_id": ObjectId(cid)})
    if updates.get("topics"):
        await _remember_topics(user["_id"], updates["topics"])
    return ser_class(doc)

@api_router.post("/classes/{cid}/audio")
async def upload_class_audio(cid: str, file: UploadFile = File(...), duration_seconds: Optional[float] = Form(None),
                              user: dict = Depends(get_current_user)):
    existing = await db.classes.find_one({"_id": ObjectId(cid), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Class not found")
    if not file.content_type or file.content_type.split(";")[0] not in CLASS_AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported audio format")
    data = await file.read()
    if len(data) > CLASS_AUDIO_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Recording is too large (max 25MB)")
    ext = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/wav": "wav"}.get(
        file.content_type.split(";")[0], "webm"
    )
    path = f"{APP_NAME}/class-audio/{user['_id']}/{cid}/{uuid.uuid4()}.{ext}"
    result = put_object(path, data, file.content_type)
    await db.files.insert_one({
        "storage_path": result["path"],
        "user_id": user["_id"],
        "content_type": file.content_type,
        "size": result.get("size"),
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    # A re-recording replaces the old one outright — one voice note per
    # class, not a growing list — so any previous transcript is stale too.
    await db.classes.update_one(
        {"_id": ObjectId(cid)},
        {"$set": {
            "audio_path": result["path"],
            "audio_duration_seconds": duration_seconds,
            "transcript": None,
            "transcript_status": "pending" if os.environ.get("OPENAI_API_KEY") else None,
        }},
    )
    doc = await db.classes.find_one({"_id": ObjectId(cid)})
    return ser_class(doc)

@api_router.delete("/classes/{cid}/audio")
async def delete_class_audio(cid: str, user: dict = Depends(get_current_user)):
    existing = await db.classes.find_one({"_id": ObjectId(cid), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Class not found")
    await db.classes.update_one(
        {"_id": ObjectId(cid)},
        {"$set": {"audio_path": None, "audio_duration_seconds": None, "transcript": None, "transcript_status": None}},
    )
    doc = await db.classes.find_one({"_id": ObjectId(cid)})
    return ser_class(doc)

@api_router.get("/classes/{cid}/audio")
async def get_class_audio(cid: str, user: dict = Depends(get_current_user)):
    existing = await db.classes.find_one({"_id": ObjectId(cid), "owner_id": user["_id"]})
    if not existing or not existing.get("audio_path"):
        raise HTTPException(status_code=404, detail="No recording on file")
    try:
        data, ct = get_object(existing["audio_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="Recording unavailable")
    return Response(content=data, media_type=ct or "audio/webm")

# --------------- FX / payment reconciliation -----------------
@api_router.get("/fx-rate")
async def fx_rate(from_currency: str = Query(..., alias="from"), to_currency: str = Query(..., alias="to"),
                   user: dict = Depends(get_current_user)):
    rate = await fx_service.get_rate(from_currency, to_currency)
    if rate is None:
        raise HTTPException(status_code=502, detail="Couldn't fetch a live exchange rate — enter the amount manually")
    return {"from": from_currency, "to": to_currency, "rate": rate}

async def _outstanding_classes(owner_id: str, student_id: str) -> list:
    """Every class for this student, oldest first, with how much of it is
    still unpaid — computed by walking prior payments' allocations (or, for
    payments recorded before allocation tracking existed, treating them as
    a lump sum applied oldest-first the same way this function itself
    allocates new payments)."""
    classes = []
    async for c in db.classes.find({"owner_id": owner_id, "student_id": student_id}).sort("class_date", 1):
        classes.append({"id": str(c["_id"]), "class_date": c["class_date"],
                         "amount": float(c.get("amount", 0)), "paid": 0.0})
    by_id = {c["id"]: c for c in classes}

    async for p in db.payments.find({"owner_id": owner_id, "student_id": student_id}).sort("paid_on", 1):
        allocations = p.get("allocations") or []
        if allocations:
            for a in allocations:
                c = by_id.get(a.get("class_id"))
                if c:
                    c["paid"] += float(a.get("amount", 0))
        else:
            # No allocation recorded (older payment, or a same-currency
            # lump sum) — apply oldest-first the same way a new payment
            # would, so the running "outstanding" figure stays consistent.
            remaining = float(p.get("amount", 0))
            for c in classes:
                if remaining <= 0:
                    break
                room = c["amount"] - c["paid"]
                if room <= 0:
                    continue
                take = min(room, remaining)
                c["paid"] += take
                remaining -= take

    return [
        {**c, "outstanding": round(c["amount"] - c["paid"], 2)}
        for c in classes
    ]

@api_router.get("/students/{sid}/reconcile-preview")
async def reconcile_preview(sid: str, received_amount: float, received_currency: str = "INR",
                             user: dict = Depends(get_current_user)):
    """Given an amount actually received (e.g. INR into the bank), convert
    it to the student's billing currency at today's rate and suggest an
    oldest-first allocation across their outstanding classes. Preview only —
    nothing is saved; the frontend lets her adjust before POSTing to
    /payments with the final allocations."""
    student = await db.students.find_one({"_id": ObjectId(sid), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    student_currency = student.get("currency", "INR")

    if student_currency == received_currency:
        converted_amount = received_amount
        rate = 1.0
    else:
        rate = await fx_service.get_rate(received_currency, student_currency)
        if rate is None:
            raise HTTPException(status_code=502, detail="Couldn't fetch a live exchange rate — enter the converted amount manually")
        converted_amount = round(received_amount * rate, 2)

    outstanding = [c for c in await _outstanding_classes(user["_id"], sid) if c["outstanding"] > 0]
    total_outstanding = round(sum(c["outstanding"] for c in outstanding), 2)

    remaining = converted_amount
    allocations = []
    for c in outstanding:
        if remaining <= 0.001:  # guard against floating-point residue (e.g. 1e-13 "remaining")
            break
        take = round(min(c["outstanding"], remaining), 2)
        allocations.append({"class_id": c["id"], "class_date": c["class_date"],
                             "class_amount": c["amount"], "outstanding_before": c["outstanding"],
                             "amount": take})
        remaining -= take

    # Two independent checks, either failing means the payment gets flagged
    # as a shortfall — see reconcile_preview's docstring context: her bank
    # only ever pays her out in INR, so received_currency is INR the vast
    # majority of the time, but the student's own currency can fluctuate
    # against INR between when she quotes a price and when it's actually
    # wired. covers_outstanding checks the student actually sent enough in
    # their own currency; meets_inr_target is a separate check against the
    # INR figure she personally expects to land in her account, which can
    # still fall short of her target even when the student sent the full
    # invoiced amount, if the bank's real conversion rate was worse than
    # what she budgeted for.
    covers_outstanding = converted_amount >= total_outstanding - 0.01
    expected_inr = student.get("expected_inr_amount")
    meets_inr_target = (
        expected_inr is None or received_currency != "INR"
        or received_amount >= expected_inr - 0.01
    )

    return {
        "student_currency": student_currency,
        "received_currency": received_currency,
        "received_amount": received_amount,
        "fx_rate": rate,
        "converted_amount": converted_amount,
        "allocations": allocations,
        "unallocated": round(max(remaining, 0), 2),  # overpayment / credit, if any
        "total_outstanding": total_outstanding,
        "covers_outstanding": covers_outstanding,
        "expected_inr_amount": expected_inr,
        "meets_inr_target": meets_inr_target,
        "is_shortfall": not (covers_outstanding and meets_inr_target),
    }

# --------------- Payments endpoints -----------------
@api_router.get("/payments")
async def list_payments(student_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"owner_id": user["_id"]}
    if student_id:
        q["student_id"] = student_id
    cur = db.payments.find(q).sort("paid_on", -1)
    out = []
    async for d in cur:
        out.append(ser_payment(d))
    return out

@api_router.post("/payments")
async def create_payment(body: PaymentCreate, user: dict = Depends(get_current_user)):
    student = await db.students.find_one(
        {"_id": ObjectId(body.student_id), "owner_id": user["_id"]}
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    doc = {
        "owner_id": user["_id"],
        "student_id": body.student_id,
        "amount": body.amount,
        "paid_on": body.paid_on,
        "method": body.method,
        "notes": body.notes,
        "received_amount": body.received_amount,
        "received_currency": body.received_currency,
        "fx_rate": body.fx_rate,
        "meets_inr_target": body.meets_inr_target,
        "allocations": [a.model_dump() for a in body.allocations],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.payments.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_payment(doc)

@api_router.delete("/payments/{pid}")
async def delete_payment(pid: str, user: dict = Depends(get_current_user)):
    res = await db.payments.delete_one({"_id": ObjectId(pid), "owner_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"ok": True}

# --------------- Dashboard / summary -----------------
async def compute_student_summary(owner_id: str, student_id: str):
    total_billed = 0.0
    total_paid = 0.0
    classes_count = 0
    hours_total = 0.0
    async for c in db.classes.find({"owner_id": owner_id, "student_id": student_id}):
        total_billed += float(c.get("amount", 0))
        hours_total += float(c.get("hours", 0))
        classes_count += 1
    async for p in db.payments.find({"owner_id": owner_id, "student_id": student_id}):
        total_paid += float(p.get("amount", 0))
    return {
        "total_billed": round(total_billed, 2),
        "total_paid": round(total_paid, 2),
        "balance_due": round(total_billed - total_paid, 2),
        "classes_count": classes_count,
        "hours_total": round(hours_total, 2),
    }

@api_router.get("/students/{sid}/summary")
async def student_summary(sid: str, user: dict = Depends(get_current_user)):
    student = await db.students.find_one({"_id": ObjectId(sid), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    summ = await compute_student_summary(user["_id"], sid)
    summ["currency"] = student.get("currency", "INR")
    return summ

# --------------- Page visit tracking (for dashboard shortcuts) -----------------
# Static labels/paths for the top-level pages. Tour pages are dynamic (one
# per tour + tab) and their labels are resolved at read time since a tour's
# name can change after a visit was recorded.
_STATIC_DEST_LABELS = {
    "students": ("Students", "/students"),
    "schedule": ("Schedule", "/schedule"),
    "classes": ("Classes", "/classes"),
    "payments": ("Payments", "/payments"),
    "invoices": ("Invoices", "/invoices"),
    "charts": ("Charts", "/charts"),
}
_TOUR_TAB_LABELS = {
    "schedule": "Schedule", "expenses": "Expenses", "invoices": "Invoices",
    "checkins": "Check-ins", "contacts": "Contacts", "todos": "To-dos", "files": "Files",
}

class VisitRecord(BaseModel):
    dest_key: str  # e.g. "students" or "tour:<tour_id>:todos"

@api_router.post("/visits")
async def record_visit(body: VisitRecord, user: dict = Depends(get_current_user)):
    dest_key = body.dest_key
    if not (dest_key in _STATIC_DEST_LABELS or dest_key.startswith("tour:")):
        raise HTTPException(status_code=400, detail="Unknown destination")
    await db.page_visits.update_one(
        {"owner_id": user["_id"], "dest_key": dest_key},
        {"$inc": {"count": 1}, "$set": {"last_visited_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}

async def _top_shortcuts(owner_id: str, limit: int = 4) -> list:
    cur = db.page_visits.find({"owner_id": owner_id}).sort("count", -1).limit(limit + 5)
    candidates = [v async for v in cur]
    tour_name_cache = {}
    out = []
    for v in candidates:
        key = v["dest_key"]
        if key in _STATIC_DEST_LABELS:
            label, path = _STATIC_DEST_LABELS[key]
        elif key.startswith("tour:"):
            _, tour_id, tab = key.split(":", 2)
            if tour_id not in tour_name_cache:
                tour_doc = await db.tours.find_one({"_id": ObjectId(tour_id), "owner_id": owner_id})
                tour_name_cache[tour_id] = tour_doc.get("name") if tour_doc else None
            tour_name = tour_name_cache[tour_id]
            if not tour_name:
                continue  # tour was deleted since — skip, don't link to a dead page
            label = f"{tour_name} — {_TOUR_TAB_LABELS.get(tab, tab.title())}"
            path = f"/tours/{tour_id}?tab={tab}"
        else:
            continue
        out.append({"dest_key": key, "label": label, "path": path, "count": v["count"]})
        if len(out) == limit:
            break
    return out

@api_router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    # Totals are grouped by currency, not blended into one number — a
    # student billing in EUR and one in INR don't sum into anything
    # meaningful together.
    totals_by_currency = {}
    student_map = {}
    async for s in db.students.find({"owner_id": user["_id"]}):
        student_map[str(s["_id"])] = s
    per_student = []
    for sid, s in student_map.items():
        summ = await compute_student_summary(user["_id"], sid)
        currency = s.get("currency", "INR")
        bucket = totals_by_currency.setdefault(currency, {"total_billed": 0.0, "total_paid": 0.0})
        bucket["total_billed"] += summ["total_billed"]
        bucket["total_paid"] += summ["total_paid"]
        per_student.append({
            "student_id": sid,
            "name": s.get("name"),
            "photo_path": s.get("photo_path"),
            "level": s.get("level"),
            "currency": currency,
            "is_active": s.get("is_active", True),
            **summ,
        })
    per_student.sort(key=lambda x: x["balance_due"], reverse=True)
    totals = [
        {
            "currency": cur,
            "total_billed": round(b["total_billed"], 2),
            "total_paid": round(b["total_paid"], 2),
            "total_due": round(b["total_billed"] - b["total_paid"], 2),
        }
        for cur, b in totals_by_currency.items()
    ]
    # INR first (the common case), then alphabetical for the rest.
    totals.sort(key=lambda t: (t["currency"] != "INR", t["currency"]))
    # recent classes
    recent = []
    cur = db.classes.find({"owner_id": user["_id"]}).sort("class_date", -1).limit(10)
    async for c in cur:
        item = ser_class(c)
        st = student_map.get(c["student_id"])
        item["student_name"] = st.get("name") if st else "Unknown"
        recent.append(item)

    # Upcoming classes still to come today, from the materialized dated
    # occurrences (not the classes log, which records classes already given,
    # and not live schedule_blocks recurrence math, which wouldn't reflect
    # one-time reschedules/cancellations from the calendar view) — entries
    # already ended or cancelled are left off, so this reads as "what's left
    # today" rather than every occurrence regardless of status/time.
    await _top_up_occurrences(user["_id"])
    now_ist = datetime.now(IST)
    today = now_ist.date()
    today_str = today.isoformat()
    now_hm = now_ist.strftime("%H:%M")
    today_classes = []
    cur = db.class_occurrences.find({
        "owner_id": user["_id"], "date": today_str, "status": "scheduled",
    }).sort("start_time", 1)
    async for occ in cur:
        if occ.get("end_time") and occ["end_time"] <= now_hm:
            continue
        names = [student_map[sid]["name"] for sid in occ.get("student_ids", []) if sid in student_map]
        today_classes.append({
            "id": str(occ["_id"]),
            "start_time": occ.get("start_time"),
            "end_time": occ.get("end_time"),
            "student_names": names,
            "is_one_off": occ.get("origin") != "recurring",
        })

    # Tour to-dos due today or overdue, still open — across every tour, so
    # she doesn't have to check each tour individually to know what's urgent.
    todos_due = []
    cur = db.tour_todos.find({
        "owner_id": user["_id"], "done": False,
        "due_date": {"$ne": None, "$lte": today_str},
    }).sort("due_date", 1)
    tour_name_cache = {}
    async for t in cur:
        tid = t["tour_id"]
        if tid not in tour_name_cache:
            tour_doc = await db.tours.find_one({"_id": ObjectId(tid)})
            tour_name_cache[tid] = tour_doc.get("name") if tour_doc else "Tour"
        todos_due.append({
            "id": str(t["_id"]),
            "tour_id": tid,
            "tour_name": tour_name_cache[tid],
            "text": t.get("text"),
            "due_date": t.get("due_date"),
            "overdue": t.get("due_date") < today_str,
        })

    shortcuts = await _top_shortcuts(user["_id"])
    active_student_count = sum(1 for s in student_map.values() if s.get("is_active", True))

    return {
        "total_students": active_student_count,
        "totals_by_currency": totals,
        "students": per_student,
        "recent_classes": recent,
        "today_classes": today_classes,
        "todos_due": todos_due,
        "shortcuts": shortcuts,
        "classes_suspended": bool(user.get("classes_suspended")),
    }

# --------------- Invoice endpoints -----------------
# PDF generation, invoice creation, date filtering and WhatsApp links have moved
# to backend/services/. These thin wrappers keep the historical function names
# so nearby handlers read naturally.

def _generate_invoice_pdf(teacher_name, student, classes, payments, summary,
                           start, end, studio_name=None, logo_bytes=None,
                           studio_contact=None, invoice_number=None, created_at=None):
    return pdf_service.generate_invoice_pdf(
        teacher_name, student, classes, payments, summary, start, end,
        studio_name=studio_name, logo_bytes=logo_bytes, studio_contact=studio_contact,
        invoice_number=invoice_number, created_at=created_at,
    )


def _filter_by_date(items, start, end, key):
    return invoices_service.filter_by_date(items, start, end, key)


async def _create_invoice_for_student(owner_id, student, start_date, end_date):
    return await invoices_service.create_invoice_for_student(
        owner_id, student, start_date, end_date,
        ser_class=ser_class, ser_payment=ser_payment, ser_student=ser_student,
    )


@api_router.post("/invoices/generate")
async def generate_invoice(body: InvoiceRequest, user: dict = Depends(get_current_user)):
    student = await db.students.find_one({"_id": ObjectId(body.student_id), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    doc = await _create_invoice_for_student(user["_id"], student, body.start_date, body.end_date)
    return {"invoice_id": doc["invoice_id"], "share_token": doc["share_token"],
            "summary": doc["summary"],
            "class_count": len(doc["classes"]), "payment_count": len(doc["payments"])}

@api_router.get("/invoices")
async def list_invoices(user: dict = Depends(get_current_user)):
    out = []
    cur = db.invoices.find({"owner_id": user["_id"]}).sort("created_at", -1).limit(200)
    async for d in cur:
        out.append({
            "invoice_id": d["invoice_id"],
            "share_token": d["share_token"],
            "student_id": d["student_id"],
            "student_name": d.get("student_snapshot", {}).get("name"),
            "summary": d.get("summary", {}),
            "start_date": d.get("start_date"),
            "end_date": d.get("end_date"),
            "created_at": d.get("created_at"),
            "last_sent_to": d.get("last_sent_to"),
            "last_sent_at": d.get("last_sent_at"),
        })
    return out

@api_router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(invoice_id: str, token: Optional[str] = Query(None),
                       request: Request = None):
    inv = await db.invoices.find_one({"invoice_id": invoice_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    # Auth: either share token (public) OR authenticated owner
    if token and token == inv["share_token"]:
        pass
    else:
        # require auth
        try:
            user = await get_current_user(request)
            if user["_id"] != inv["owner_id"]:
                raise HTTPException(status_code=403, detail="Not authorized")
        except HTTPException:
            raise HTTPException(status_code=401, detail="Not authenticated")
    studio = inv.get("studio_snapshot") or {}
    logo_bytes = None
    if studio.get("logo_path"):
        try:
            logo_bytes, _ = get_object(studio["logo_path"])
        except Exception as e:
            logger.warning(f"Logo fetch failed for invoice {invoice_id}: {e}")
    pdf_bytes = _generate_invoice_pdf(
        inv.get("teacher_name") or "Dance Teacher",
        inv["student_snapshot"], inv["classes"], inv["payments"], inv["summary"],
        inv.get("start_date"), inv.get("end_date"),
        studio_name=studio.get("studio_name"),
        logo_bytes=logo_bytes,
        studio_contact=studio,
        invoice_number=inv.get("invoice_number"),
        created_at=inv.get("created_at"),
    )
    filename = f"invoice_{invoice_id}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{filename}"'})

@api_router.get("/invoices/share/{share_token}")
async def get_shared_invoice(share_token: str):
    inv = await db.invoices.find_one({"share_token": share_token})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {
        "invoice_id": inv["invoice_id"],
        "invoice_number": inv.get("invoice_number"),
        "share_token": inv["share_token"],
        "teacher_name": inv.get("teacher_name"),
        "studio": inv.get("studio_snapshot") or {},
        "student": inv["student_snapshot"],
        "classes": inv["classes"],
        "payments": inv["payments"],
        "summary": inv["summary"],
        "start_date": inv.get("start_date"),
        "end_date": inv.get("end_date"),
        "created_at": inv.get("created_at"),
    }

@api_router.get("/invoices/share/{share_token}/logo")
async def shared_invoice_logo(share_token: str):
    inv = await db.invoices.find_one({"share_token": share_token})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    logo_path = (inv.get("studio_snapshot") or {}).get("logo_path")
    if not logo_path:
        raise HTTPException(status_code=404, detail="No logo")
    try:
        data, ct = get_object(logo_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Logo unavailable")
    return Response(content=data, media_type=ct or "image/png")

@api_router.get("/invoices/share/{share_token}/qr")
async def shared_invoice_qr(share_token: str):
    # Same scannable UPI QR as the PDF — only meaningful when there's a
    # balance still due and a UPI ID on file.
    inv = await db.invoices.find_one({"share_token": share_token})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    balance_due = (inv.get("summary") or {}).get("balance_due", 0)
    upi_vpa = (inv.get("studio_snapshot") or {}).get("contact_upi")
    if not upi_vpa or balance_due <= 0:
        raise HTTPException(status_code=404, detail="No QR available")
    qr_bytes = pdf_service.upi_qr_bytes(upi_vpa, inv.get("teacher_name") or "", balance_due)
    if not qr_bytes:
        raise HTTPException(status_code=404, detail="QR generation failed")
    return Response(content=qr_bytes, media_type="image/png")

class BulkSendRequest(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    student_ids: Optional[List[str]] = None  # explicit selection; if None => all outstanding
    channels: List[str] = Field(default_factory=lambda: ["email"])  # 'email' and/or 'whatsapp'
    public_link_base: str
    message: Optional[str] = None


@api_router.get("/invoices/bulk-preview")
async def bulk_preview(start_date: Optional[str] = None, end_date: Optional[str] = None,
                       user: dict = Depends(get_current_user)):
    """Return per-student outstanding balance + reachability channels for bulk-send."""
    students = []
    async for s in db.students.find({"owner_id": user["_id"]}):
        students.append(s)
    out = []
    for s in students:
        sid = str(s["_id"])
        summ = await compute_student_summary(user["_id"], sid)
        # optionally recompute against the requested date window using totals
        billed_win, paid_win = 0.0, 0.0
        if start_date or end_date:
            async for c in db.classes.find({"owner_id": user["_id"], "student_id": sid}):
                d = c.get("class_date") or ""
                if start_date and d < start_date: continue
                if end_date and d > end_date: continue
                billed_win += float(c.get("amount", 0))
            async for p in db.payments.find({"owner_id": user["_id"], "student_id": sid}):
                d = p.get("paid_on") or ""
                if start_date and d < start_date: continue
                if end_date and d > end_date: continue
                paid_win += float(p.get("amount", 0))
            balance_in_window = round(billed_win - paid_win, 2)
        else:
            balance_in_window = summ["balance_due"]

        out.append({
            "student_id": sid,
            "name": s.get("name"),
            "email": s.get("email"),
            "phone": s.get("phone"),
            "currency": s.get("currency", "INR"),
            "is_active": s.get("is_active", True),
            "balance_due": summ["balance_due"],       # overall
            "window_billed": round(billed_win, 2) if (start_date or end_date) else summ["total_billed"],
            "window_balance": balance_in_window,
            "channels": [ch for ch, ok in [("email", bool(s.get("email"))), ("whatsapp", bool(s.get("phone")))] if ok],
        })
    out.sort(key=lambda x: x["balance_due"], reverse=True)
    return out


def _wa_link(phone: str, message: str) -> str:
    return invoices_service.wa_link(phone, message)


@api_router.post("/invoices/bulk-send")
async def bulk_send(body: BulkSendRequest, user: dict = Depends(get_current_user)):
    """Generate an invoice for each targeted student and send it on the selected channels.
    For 'email', the send happens server-side. For 'whatsapp', we return a pre-filled
    wa.me link that the frontend can open in new tabs.
    """
    origin = body.public_link_base.rstrip("/")

    # Determine target students
    filter_q = {"owner_id": user["_id"]}
    if body.student_ids:
        try:
            filter_q["_id"] = {"$in": [ObjectId(sid) for sid in body.student_ids]}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid student id in list")
    students = []
    async for s in db.students.find(filter_q):
        students.append(s)

    if not body.channels:
        raise HTTPException(status_code=400, detail="At least one channel is required")
    channels = set(body.channels)
    if not channels.issubset({"email", "whatsapp"}):
        raise HTTPException(status_code=400, detail="Unknown channel")

    results = []
    for s in students:
        sid = str(s["_id"])
        # Always skip students with no outstanding balance (whether they were
        # hand-picked or matched by the "all outstanding" default).
        summ = await compute_student_summary(user["_id"], sid)
        if summ["balance_due"] <= 0:
            continue

        try:
            doc = await _create_invoice_for_student(user["_id"], s, body.start_date, body.end_date)
        except Exception as e:
            results.append({"student_id": sid, "name": s.get("name"), "status": "error",
                            "detail": f"Invoice generation failed: {e}"})
            continue

        entry = {
            "student_id": sid,
            "name": s.get("name"),
            "invoice_id": doc["invoice_id"],
            "share_token": doc["share_token"],
            "public_link": f"{origin}/invoice/{doc['share_token']}",
            "balance_due": doc["summary"]["balance_due"],
            "currency": s.get("currency", "INR"),
            "channels": {},
        }

        # Email channel
        if "email" in channels:
            if not s.get("email"):
                entry["channels"]["email"] = {"status": "skipped", "reason": "no email on file"}
            elif not EMAIL_KEY:
                entry["channels"]["email"] = {"status": "skipped", "reason": "email not configured"}
            else:
                send_body = SendInvoiceRequest(
                    to_email=s["email"],
                    public_link=entry["public_link"],
                    message=body.message,
                )
                payload = _build_email_payload(doc, send_body, doc["invoice_id"])
                try:
                    await _dispatch_email(payload)
                    await _mark_invoice_sent(doc["invoice_id"], s["email"])
                    entry["channels"]["email"] = {"status": "sent", "to": s["email"]}
                except Exception as e:
                    logger.error(f"Bulk email failed for {sid}: {e}")
                    entry["channels"]["email"] = {"status": "error", "detail": "email dispatch failed"}

        # WhatsApp channel: return pre-filled link for the frontend to open
        if "whatsapp" in channels:
            if not s.get("phone"):
                entry["channels"]["whatsapp"] = {"status": "skipped", "reason": "no phone on file"}
            else:
                teacher = doc.get("studio_snapshot", {}).get("studio_name") or doc.get("teacher_name") or "your teacher"
                symbol = CURRENCY_SYMBOLS.get(s.get("currency", "INR"), (s.get("currency") or "") + " ")
                msg = (f"Hi {s.get('name') or ''}, here's your invoice from {teacher} "
                       f"({symbol}{doc['summary']['balance_due']} due):\n{entry['public_link']}")
                entry["channels"]["whatsapp"] = {"status": "ready", "url": _wa_link(s["phone"], msg)}

        results.append(entry)

    summary_counts = {
        "students": len(results),
        "emails_sent": sum(1 for r in results if r.get("channels", {}).get("email", {}).get("status") == "sent"),
        "whatsapp_links": sum(1 for r in results if r.get("channels", {}).get("whatsapp", {}).get("status") == "ready"),
    }
    return {"summary": summary_counts, "results": results}


@api_router.delete("/invoices/{invoice_id}")
async def delete_invoice(invoice_id: str, user: dict = Depends(get_current_user)):
    res = await db.invoices.delete_one({"invoice_id": invoice_id, "owner_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"ok": True}

@api_router.get("/")
async def root():
    return {"message": "Dance Billing API"}

# --------------- Stats / charts -----------------
@api_router.get("/stats/monthly")
async def stats_monthly(months: int = 6, user: dict = Depends(get_current_user)):
    # Build list of last N months (YYYY-MM keys)
    now = datetime.now(timezone.utc).replace(day=1)
    month_keys = []
    y, m = now.year, now.month
    for _ in range(months):
        month_keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_keys.reverse()

    earnings = {k: 0.0 for k in month_keys}
    hours = {k: 0.0 for k in month_keys}
    async for c in db.classes.find({"owner_id": user["_id"]}):
        d = c.get("class_date") or ""
        key = d[:7] if len(d) >= 7 else None
        if key in earnings:
            earnings[key] += float(c.get("amount", 0))
            hours[key] += float(c.get("hours", 0))

    return {
        "months": month_keys,
        "series": [
            {"month": k, "earnings": round(earnings[k], 2), "hours": round(hours[k], 2)}
            for k in month_keys
        ],
    }

@api_router.get("/stats/by-student")
async def stats_by_student(user: dict = Depends(get_current_user)):
    smap = {}
    async for s in db.students.find({"owner_id": user["_id"]}):
        smap[str(s["_id"])] = s.get("name") or "—"
    agg = defaultdict(lambda: {"hours": 0.0, "amount": 0.0})
    async for c in db.classes.find({"owner_id": user["_id"]}):
        sid = c.get("student_id")
        agg[sid]["hours"] += float(c.get("hours", 0))
        agg[sid]["amount"] += float(c.get("amount", 0))
    out = []
    for sid, v in agg.items():
        out.append({
            "student_id": sid,
            "name": smap.get(sid, "Unknown"),
            "hours": round(v["hours"], 2),
            "amount": round(v["amount"], 2),
        })
    out.sort(key=lambda x: x["amount"], reverse=True)
    return out

# --------------- Invoice send (Resend email) -----------------
class SendInvoiceRequest(BaseModel):
    to_email: EmailStr
    reply_to: Optional[EmailStr] = None
    message: Optional[str] = None
    public_link: str  # frontend-hosted /invoice/<share_token>

def _build_invoice_email_html(inv, public_link, pdf_link, teacher_name, personal_note):
    return email_service.build_invoice_email_html(
        inv, public_link, pdf_link, teacher_name, personal_note
    )


def _build_email_payload(inv, body, invoice_id):
    return email_service.build_invoice_email_payload(
        inv, invoice_id, body.to_email, body.public_link, body.message, body.reply_to
    )


async def _dispatch_email(payload):
    return await email_service.dispatch_email(payload)


async def _mark_invoice_sent(invoice_id, to_email):
    await email_service.mark_invoice_sent(invoice_id, to_email)


@api_router.post("/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, body: SendInvoiceRequest,
                       user: dict = Depends(get_current_user)):
    if not EMAIL_KEY:
        raise HTTPException(status_code=503, detail="Email is not configured")
    inv = await db.invoices.find_one({"invoice_id": invoice_id, "owner_id": user["_id"]})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    payload = _build_email_payload(inv, body, invoice_id)
    try:
        result = await _dispatch_email(payload)
    except httpx.HTTPStatusError as e:
        logger.error(f"Email send failed: {e.response.status_code} {e.response.text}")
        raise HTTPException(status_code=502, detail="Failed to send email")
    except Exception as e:
        logger.error(f"Email error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email")

    await _mark_invoice_sent(invoice_id, body.to_email)
    student_name = inv.get("student_snapshot", {}).get("name") or "student"
    return {"status": "sent", "to": body.to_email, "student": student_name,
            "email_id": result.get("id")}

# --------------- Schedule endpoints -----------------
def _time_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def _blocks_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end

async def _assert_no_overlap(owner_id: str, day_of_week: int, start_time: str,
                              end_time: str, exclude_id: Optional[str] = None):
    start_m = _time_to_minutes(start_time)
    end_m = _time_to_minutes(end_time)
    if end_m <= start_m:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")
    query = {"owner_id": owner_id, "day_of_week": day_of_week}
    async for b in db.schedule_blocks.find(query):
        if exclude_id and str(b["_id"]) == exclude_id:
            continue
        if _blocks_overlap(start_m, end_m, _time_to_minutes(b["start_time"]), _time_to_minutes(b["end_time"])):
            raise HTTPException(status_code=409, detail="This overlaps an existing schedule block")

def _next_occurrence(day_of_week: int) -> str:
    """Next upcoming date (including today) for the given weekday, as an ISO
    date string — same anchoring logic Calendar sync uses for the first
    occurrence of a recurring block, reused here for one-offs since a
    one-off's only occurrence IS that anchor date."""
    today = date.today()
    days_ahead = (day_of_week - today.weekday()) % 7
    return (today + timedelta(days=days_ahead)).isoformat()

async def _prune_expired_one_offs(owner_id: str):
    """One-off blocks disappear on their own after their single occurrence
    has passed — no manual cleanup needed. Deleted lazily on schedule reads
    rather than via a separate cron, since there's no other reason to poll
    this collection on a timer."""
    today_str = date.today().isoformat()
    async for b in db.schedule_blocks.find({
        "owner_id": owner_id, "is_one_off": True, "occurs_on": {"$lt": today_str},
    }):
        await calendar_service.sync_block_delete(owner_id, b.get("google_event_id"))
        await db.schedule_blocks.delete_one({"_id": b["_id"]})

# --------------- Class occurrences (dated calendar) -----------------
# class_occurrences materializes schedule_blocks into one document per dated
# instance, rolling OCCURRENCE_HORIZON_DAYS ahead. This is the single source
# of truth for "what's happening on date X" — the day/week/month calendar
# view, clash detection against personal events, dashboard "today", and
# student notifications all read this collection, never live day_of_week
# recurrence math. A one-time reschedule/cancel just edits one occurrence
# document and never touches schedule_blocks, so it can never leak back into
# the recurring pattern.
OCCURRENCE_HORIZON_DAYS = 56  # ~8 weeks

async def _generate_occurrences_for_block(owner_id: str, block: dict, horizon_days: int = OCCURRENCE_HORIZON_DAYS):
    """(Re)generates untouched future occurrences for one recurring block, out
    to the horizon. Only ever inserts occurrences that don't already exist for
    that (block_id, date) — an occurrence that was individually rescheduled or
    cancelled (status != "scheduled", or origin != "recurring") is already
    detached from the block and is never touched here. is_one_off blocks get
    exactly one occurrence, on their occurs_on date, regardless of horizon."""
    block_id = str(block["_id"])
    today = date.today()

    if block.get("is_one_off"):
        occurs_on = block.get("occurs_on")
        if not occurs_on or occurs_on < today.isoformat():
            return
        dates = [occurs_on]
    else:
        day_of_week = block["day_of_week"]
        days_ahead = (day_of_week - today.weekday()) % 7
        first = today + timedelta(days=days_ahead)
        dates = []
        d = first
        while (d - today).days <= horizon_days:
            dates.append(d.isoformat())
            d += timedelta(days=7)

    for d_str in dates:
        existing = await db.class_occurrences.find_one({"block_id": block_id, "date": d_str})
        if existing:
            # Only refresh a still-untouched occurrence — one that's been
            # individually rescheduled/cancelled must never be overwritten.
            if existing.get("status") == "scheduled" and existing.get("origin") == "recurring":
                await db.class_occurrences.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {
                        "start_time": block["start_time"], "end_time": block["end_time"],
                        "student_ids": block.get("student_ids", []), "notes": block.get("notes"),
                    }},
                )
            continue
        await db.class_occurrences.insert_one({
            "owner_id": owner_id,
            "block_id": block_id,
            "date": d_str,
            "start_time": block["start_time"],
            "end_time": block["end_time"],
            "student_ids": block.get("student_ids", []),
            "notes": block.get("notes"),
            "status": "scheduled",
            "origin": "recurring",
            "moved_from_date": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

async def _regenerate_block_occurrences(owner_id: str, block: dict):
    """Called right after a schedule_blocks create/update. Drops future
    untouched (still-"scheduled"/"recurring") occurrences for this block so
    they get recreated at the new day/time, then regenerates. Occurrences
    already detached by an individual reschedule/cancel — or already in the
    past — are left exactly alone."""
    block_id = str(block["_id"])
    today_str = date.today().isoformat()
    await db.class_occurrences.delete_many({
        "block_id": block_id, "date": {"$gte": today_str},
        "status": "scheduled", "origin": "recurring",
    })
    await _generate_occurrences_for_block(owner_id, block)

async def _top_up_occurrences(owner_id: str):
    """Extends every recurring block's occurrences out to the rolling
    horizon — called by the daily cron. Doesn't touch one-off blocks beyond
    their single occurrence, and never overwrites detached occurrences."""
    async for b in db.schedule_blocks.find({"owner_id": owner_id, "is_one_off": {"$ne": True}}):
        await _generate_occurrences_for_block(owner_id, b)

@api_router.get("/schedule")
async def list_schedule(user: dict = Depends(get_current_user)):
    await _prune_expired_one_offs(user["_id"])
    cur = db.schedule_blocks.find({"owner_id": user["_id"]}).sort("start_time", 1)
    out = []
    async for d in cur:
        out.append(ser_schedule_block(d))
    return out

async def _student_names(owner_id: str, student_ids: List[str]) -> List[str]:
    names = []
    for sid in student_ids:
        s = await db.students.find_one({"_id": ObjectId(sid), "owner_id": owner_id})
        if s:
            names.append(s.get("name") or "Student")
    return names

@api_router.post("/schedule")
async def create_schedule_block(body: ScheduleBlockCreate, user: dict = Depends(get_current_user)):
    if not (0 <= body.day_of_week <= 6):
        raise HTTPException(status_code=400, detail="day_of_week must be 0-6")
    if not body.student_ids:
        raise HTTPException(status_code=400, detail="student_ids must not be empty")
    await _assert_no_overlap(user["_id"], body.day_of_week, body.start_time, body.end_time)
    doc = body.model_dump()
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    if doc.get("is_one_off"):
        doc["occurs_on"] = _next_occurrence(body.day_of_week)
    res = await db.schedule_blocks.insert_one(doc)
    doc["_id"] = res.inserted_id

    names = await _student_names(user["_id"], doc["student_ids"])
    event_id = await calendar_service.sync_block_upsert(user["_id"], doc, names)
    if event_id:
        await db.schedule_blocks.update_one({"_id": doc["_id"]}, {"$set": {"google_event_id": event_id}})
        doc["google_event_id"] = event_id
    await _generate_occurrences_for_block(user["_id"], doc)
    return ser_schedule_block(doc)

@api_router.patch("/schedule/{block_id}")
async def update_schedule_block(block_id: str, body: ScheduleBlockUpdate, user: dict = Depends(get_current_user)):
    existing = await db.schedule_blocks.find_one({"_id": ObjectId(block_id), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule block not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "student_ids" in updates and not updates["student_ids"]:
        raise HTTPException(status_code=400, detail="student_ids must not be empty")

    day_of_week = updates.get("day_of_week", existing["day_of_week"])
    start_time = updates.get("start_time", existing["start_time"])
    end_time = updates.get("end_time", existing["end_time"])
    await _assert_no_overlap(user["_id"], day_of_week, start_time, end_time, exclude_id=block_id)

    is_one_off = updates.get("is_one_off", existing.get("is_one_off", False))
    if is_one_off and ("day_of_week" in updates or "is_one_off" in updates):
        updates["occurs_on"] = _next_occurrence(day_of_week)
    elif not is_one_off and "is_one_off" in updates:
        updates["occurs_on"] = None  # turned back into a recurring block

    await db.schedule_blocks.update_one({"_id": ObjectId(block_id)}, {"$set": updates})
    doc = await db.schedule_blocks.find_one({"_id": ObjectId(block_id)})

    names = await _student_names(user["_id"], doc["student_ids"])
    event_id = await calendar_service.sync_block_upsert(user["_id"], doc, names)
    if event_id and event_id != doc.get("google_event_id"):
        await db.schedule_blocks.update_one({"_id": doc["_id"]}, {"$set": {"google_event_id": event_id}})
        doc["google_event_id"] = event_id

    # Only the day/time actually moving is worth a push — not every metadata
    # edit (notes, is_one_off toggling without a day change, etc).
    if day_of_week != existing["day_of_week"] or start_time != existing["start_time"] or end_time != existing["end_time"]:
        when = f"{_WEEKDAY_NAMES[day_of_week]} {start_time}"
        for sid in doc["student_ids"]:
            await push_service.send_push(
                "student", sid,
                "Class rescheduled", f"Your teacher moved this class to {when}", "/portal/schedule",
            )
    await _regenerate_block_occurrences(user["_id"], doc)
    return ser_schedule_block(doc)

@api_router.delete("/schedule/{block_id}")
async def delete_schedule_block(block_id: str, user: dict = Depends(get_current_user)):
    existing = await db.schedule_blocks.find_one({"_id": ObjectId(block_id), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule block not found")
    await calendar_service.sync_block_delete(user["_id"], existing.get("google_event_id"))
    await db.schedule_blocks.delete_one({"_id": ObjectId(block_id), "owner_id": user["_id"]})
    today_str = date.today().isoformat()
    await db.class_occurrences.delete_many({
        "block_id": block_id, "date": {"$gte": today_str},
        "status": "scheduled", "origin": "recurring",
    })
    for sid in existing.get("student_ids", []):
        await push_service.send_push(
            "student", sid,
            "Class cancelled", "Your teacher removed this class from the schedule", "/portal/schedule",
        )
    return {"ok": True}

# --------------- Calendar (dated occurrences + personal events) -----------------
# The day/week/month calendar view. Reads class_occurrences (materialized
# dated class instances) and personal_events (Lakshmi's own non-class
# engagements) side by side for a date range. Rescheduling/cancelling one
# occurrence here is a direct, instant, one-time edit to that single document
# — it never touches schedule_blocks (the recurring master pattern) and
# never affects any other occurrence.

async def _personal_events_overlap(owner_id: str, d_str: str, start_time: str, end_time: str) -> bool:
    start_m = _time_to_minutes(start_time)
    end_m = _time_to_minutes(end_time)
    async for ev in db.personal_events.find({"owner_id": owner_id, "date": d_str}):
        if _blocks_overlap(start_m, end_m, _time_to_minutes(ev["start_time"]), _time_to_minutes(ev["end_time"])):
            return True
    return False

async def _occurrences_overlap(owner_id: str, d_str: str, start_time: str, end_time: str,
                                exclude_occurrence_id: Optional[str] = None) -> bool:
    start_m = _time_to_minutes(start_time)
    end_m = _time_to_minutes(end_time)
    async for occ in db.class_occurrences.find({"owner_id": owner_id, "date": d_str, "status": "scheduled"}):
        if exclude_occurrence_id and str(occ["_id"]) == exclude_occurrence_id:
            continue
        if _blocks_overlap(start_m, end_m, _time_to_minutes(occ["start_time"]), _time_to_minutes(occ["end_time"])):
            return True
    return False

@api_router.get("/calendar/occurrences")
async def list_occurrences(start: str = Query(...), end: str = Query(...), user: dict = Depends(get_current_user)):
    """All dated class occurrences for the owner between start and end
    (inclusive ISO dates) — the data source for the month/week/day calendar
    grid."""
    await _top_up_occurrences(user["_id"])
    student_map = {}
    async for s in db.students.find({"owner_id": user["_id"]}):
        student_map[str(s["_id"])] = s.get("name") or "Student"
    out = []
    cur = db.class_occurrences.find({
        "owner_id": user["_id"], "date": {"$gte": start, "$lte": end},
    }).sort([("date", 1), ("start_time", 1)])
    async for occ in cur:
        item = ser_occurrence(occ)
        item["student_names"] = [student_map.get(sid, "Student") for sid in occ.get("student_ids", [])]
        out.append(item)
    return out

@api_router.get("/calendar/personal-events")
async def list_personal_events(start: str = Query(...), end: str = Query(...), user: dict = Depends(get_current_user)):
    cur = db.personal_events.find({
        "owner_id": user["_id"], "date": {"$gte": start, "$lte": end},
    }).sort([("date", 1), ("start_time", 1)])
    out = []
    async for ev in cur:
        out.append(ser_personal_event(ev))
    return out

@api_router.post("/calendar/personal-events")
async def create_personal_event(body: PersonalEventCreate, user: dict = Depends(get_current_user)):
    if _time_to_minutes(body.end_time) <= _time_to_minutes(body.start_time):
        raise HTTPException(status_code=400, detail="end_time must be after start_time")
    doc = body.model_dump()
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.personal_events.insert_one(doc)
    doc["_id"] = res.inserted_id

    clash = await _occurrences_overlap(user["_id"], body.date, body.start_time, body.end_time)
    result = ser_personal_event(doc)
    result["clashes_with_classes"] = clash
    return result

@api_router.patch("/calendar/personal-events/{event_id}")
async def update_personal_event(event_id: str, body: PersonalEventUpdate, user: dict = Depends(get_current_user)):
    existing = await db.personal_events.find_one({"_id": ObjectId(event_id), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Event not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    start_time = updates.get("start_time", existing["start_time"])
    end_time = updates.get("end_time", existing["end_time"])
    if _time_to_minutes(end_time) <= _time_to_minutes(start_time):
        raise HTTPException(status_code=400, detail="end_time must be after start_time")
    await db.personal_events.update_one({"_id": ObjectId(event_id)}, {"$set": updates})
    doc = await db.personal_events.find_one({"_id": ObjectId(event_id)})
    clash = await _occurrences_overlap(user["_id"], doc["date"], doc["start_time"], doc["end_time"])
    result = ser_personal_event(doc)
    result["clashes_with_classes"] = clash
    return result

@api_router.delete("/calendar/personal-events/{event_id}")
async def delete_personal_event(event_id: str, user: dict = Depends(get_current_user)):
    res = await db.personal_events.delete_one({"_id": ObjectId(event_id), "owner_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"ok": True}

@api_router.post("/calendar/occurrences/{occurrence_id}/reschedule")
async def reschedule_occurrence(occurrence_id: str, body: OccurrenceRescheduleRequest, user: dict = Depends(get_current_user)):
    """Lakshmi moving one dated class occurrence herself — direct and
    instant (no approval step, unlike the student change-request flow).
    Only this single occurrence is affected; the recurring schedule_blocks
    pattern this occurrence came from is untouched, so every other
    occurrence of that block keeps its original day/time."""
    occ = await db.class_occurrences.find_one({"_id": ObjectId(occurrence_id), "owner_id": user["_id"]})
    if not occ:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    if occ.get("status") != "scheduled":
        raise HTTPException(status_code=400, detail="This class is already cancelled or moved")
    if _time_to_minutes(body.end_time) <= _time_to_minutes(body.start_time):
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    clash = await _occurrences_overlap(user["_id"], body.date, body.start_time, body.end_time,
                                        exclude_occurrence_id=occurrence_id)
    if not clash:
        clash = await _personal_events_overlap(user["_id"], body.date, body.start_time, body.end_time)
    if clash:
        raise HTTPException(status_code=409, detail="That time clashes with another class or a personal event")

    await db.class_occurrences.update_one(
        {"_id": occ["_id"]},
        {"$set": {
            "date": body.date, "start_time": body.start_time, "end_time": body.end_time,
            "origin": "rescheduled", "moved_from_date": occ["date"],
            "moved_from_start_time": occ["start_time"], "moved_from_end_time": occ["end_time"],
        }},
    )
    updated = await db.class_occurrences.find_one({"_id": occ["_id"]})
    when = f"{body.date} {body.start_time}"
    for sid in occ.get("student_ids", []):
        await push_service.send_push(
            "student", sid,
            "Class rescheduled", f"Your class on {occ['date']} was moved to {when}", "/portal/calendar",
        )
    return ser_occurrence(updated)

@api_router.post("/calendar/occurrences/{occurrence_id}/undo-reschedule")
async def undo_reschedule_occurrence(occurrence_id: str, user: dict = Depends(get_current_user)):
    """Reverts the most recent reschedule — puts the occurrence back on its
    moved_from_date/start_time/end_time and clears the "moved" trail. Only
    one level deep: undoing after two reschedules in a row lands on the
    state right before the second move, not the original slot, matching
    what "undo" means for the change the teacher just made."""
    occ = await db.class_occurrences.find_one({"_id": ObjectId(occurrence_id), "owner_id": user["_id"]})
    if not occ:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    if occ.get("origin") != "rescheduled" or not occ.get("moved_from_date"):
        raise HTTPException(status_code=400, detail="This class hasn't been rescheduled")
    prev_date = occ["moved_from_date"]
    prev_start = occ["moved_from_start_time"]
    prev_end = occ["moved_from_end_time"]

    clash = await _occurrences_overlap(user["_id"], prev_date, prev_start, prev_end,
                                        exclude_occurrence_id=occurrence_id)
    if not clash:
        clash = await _personal_events_overlap(user["_id"], prev_date, prev_start, prev_end)
    if clash:
        raise HTTPException(status_code=409, detail="That original slot is no longer free — something else was scheduled since")

    await db.class_occurrences.update_one(
        {"_id": occ["_id"]},
        {"$set": {
            "date": prev_date, "start_time": prev_start, "end_time": prev_end,
            "origin": "recurring", "moved_from_date": None,
            "moved_from_start_time": None, "moved_from_end_time": None,
        }},
    )
    updated = await db.class_occurrences.find_one({"_id": occ["_id"]})
    for sid in occ.get("student_ids", []):
        await push_service.send_push(
            "student", sid,
            "Class reschedule undone", f"Your class is back to {prev_date} {prev_start}", "/portal/calendar",
        )
    return ser_occurrence(updated)

@api_router.post("/calendar/occurrences/{occurrence_id}/cancel")
async def cancel_occurrence(occurrence_id: str, user: dict = Depends(get_current_user)):
    occ = await db.class_occurrences.find_one({"_id": ObjectId(occurrence_id), "owner_id": user["_id"]})
    if not occ:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    if occ.get("status") != "scheduled":
        raise HTTPException(status_code=400, detail="This class is already cancelled or moved")
    await db.class_occurrences.update_one({"_id": occ["_id"]}, {"$set": {"status": "cancelled"}})
    for sid in occ.get("student_ids", []):
        await push_service.send_push(
            "student", sid,
            "Class cancelled", f"Your class on {occ['date']} was cancelled", "/portal/calendar",
        )
    return {"ok": True}

@api_router.post("/calendar/occurrences/{occurrence_id}/restore")
async def restore_occurrence(occurrence_id: str, user: dict = Depends(get_current_user)):
    """Undo a cancel — only while it's still a same-slot cancellation (not
    yet reworked into a reschedule elsewhere)."""
    occ = await db.class_occurrences.find_one({"_id": ObjectId(occurrence_id), "owner_id": user["_id"]})
    if not occ:
        raise HTTPException(status_code=404, detail="Occurrence not found")
    if occ.get("status") != "cancelled":
        raise HTTPException(status_code=400, detail="This class isn't cancelled")
    clash = await _occurrences_overlap(user["_id"], occ["date"], occ["start_time"], occ["end_time"],
                                        exclude_occurrence_id=occurrence_id)
    if not clash:
        clash = await _personal_events_overlap(user["_id"], occ["date"], occ["start_time"], occ["end_time"])
    if clash:
        raise HTTPException(status_code=409, detail="That slot is no longer free — something else was scheduled since")
    await db.class_occurrences.update_one({"_id": occ["_id"]}, {"$set": {"status": "scheduled"}})
    updated = await db.class_occurrences.find_one({"_id": occ["_id"]})
    return ser_occurrence(updated)

# --------------- Student portal -----------------
# Students get their own login to view their own schedule/dues/progress,
# request a cancellation or reschedule (with 24h notice), keep private notes,
# and upload proof of payment. Onboarding is invite-only: the teacher sends an
# invite link (see /students/{sid}/send-portal-invite below) that logs the
# student in immediately and forces them to set a password; every login after
# that is plain email + password, with the same forgot/reset-password flow
# the teacher uses. Kept as one section (models + helpers + routes together)
# since it's a single cohesive feature layered on top of the teacher-owned
# data above.

class StudentAcceptInviteRequest(BaseModel):
    token: str

class StudentSetPasswordRequest(BaseModel):
    password: str

class StudentLoginRequest(BaseModel):
    email: EmailStr
    password: str

class StudentSelfUpdate(BaseModel):
    photo_path: Optional[str] = None

class StudentNoteCreate(BaseModel):
    text: str

class StudentNoteUpdate(BaseModel):
    text: str

class ChangeRequestCreate(BaseModel):
    block_id: str
    type: str  # "cancel" | "reschedule"
    scope: str  # "one_time" | "permanent"
    requested_day_of_week: Optional[int] = None
    requested_start_time: Optional[str] = None
    requested_end_time: Optional[str] = None
    reason: Optional[str] = None

class ChangeRequestDeny(BaseModel):
    reason: Optional[str] = None

CHANGE_REQUEST_TYPES = {"cancel", "reschedule"}
CHANGE_REQUEST_SCOPES = {"one_time", "permanent"}
PAYMENT_PROOF_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
PAYMENT_PROOF_MAX_BYTES = 10 * 1024 * 1024

def ser_schedule_block_for_student(doc, next_occurrence=None, next_occurrence_start=None):
    # Deliberately omits student_ids — a student must never learn who else is
    # on a shared block.
    return {
        "id": str(doc["_id"]),
        "day_of_week": doc.get("day_of_week"),
        "start_time": doc.get("start_time"),
        "end_time": doc.get("end_time"),
        "notes": doc.get("notes"),
        "is_one_off": doc.get("is_one_off", False),
        "next_occurrence": next_occurrence,
        "next_occurrence_start": next_occurrence_start,
    }

def ser_student_note(doc):
    return {
        "id": str(doc["_id"]),
        "text": doc.get("text"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

def ser_change_request(doc):
    return {
        "id": str(doc["_id"]),
        "student_id": doc.get("student_id"),
        "block_id": doc.get("block_id"),
        "occurs_on": doc.get("occurs_on"),
        "type": doc.get("type"),
        "scope": doc.get("scope"),
        "requested_day_of_week": doc.get("requested_day_of_week"),
        "requested_start_time": doc.get("requested_start_time"),
        "requested_end_time": doc.get("requested_end_time"),
        "reason": doc.get("reason"),
        "status": doc.get("status"),
        "denial_reason": doc.get("denial_reason"),
        "auto_denied": doc.get("auto_denied", False),
        "created_at": doc.get("created_at"),
        "decided_at": doc.get("decided_at"),
    }

def ser_payment_proof(doc):
    return {
        "id": str(doc["_id"]),
        "student_id": doc.get("student_id"),
        "content_type": doc.get("content_type"),
        "amount_claimed": doc.get("amount_claimed"),
        "note": doc.get("note"),
        "status": doc.get("status"),
        "uploaded_at": doc.get("uploaded_at"),
    }

# --------------- Student auth helpers -----------------
def create_student_access_token(student_id: str, owner_id: str) -> str:
    payload = {"sub": student_id, "owner_id": owner_id,
               "exp": datetime.now(timezone.utc) + timedelta(hours=8),
               "type": "student_access"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def create_student_refresh_token(student_id: str, owner_id: str) -> str:
    payload = {"sub": student_id, "owner_id": owner_id,
               "exp": datetime.now(timezone.utc) + timedelta(days=30),
               "type": "student_refresh"}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)

def set_student_auth_cookies(response: Response, access: str, refresh: str):
    # Separate cookie names from the teacher's access_token/refresh_token so
    # a teacher previewing the portal in the same browser can't collide
    # sessions with their own login.
    response.set_cookie("student_access_token", access, httponly=True, secure=True,
                        samesite="none", max_age=8 * 3600, path="/")
    response.set_cookie("student_refresh_token", refresh, httponly=True, secure=True,
                        samesite="none", max_age=30 * 24 * 3600, path="/")

async def get_current_student(request: Request) -> dict:
    token = request.cookies.get("student_access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "student_access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        student = await db.students.find_one({
            "_id": ObjectId(payload["sub"]), "owner_id": payload["owner_id"],
        })
        if not student or student.get("is_active") is False:
            raise HTTPException(status_code=401, detail="Student not found")
        student["_id"] = str(student["_id"])
        student["_has_password"] = bool(student.get("password_hash"))
        student.pop("password_hash", None)
        return student
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@api_router.post("/student/auth/accept-invite")
async def student_accept_invite(body: StudentAcceptInviteRequest, response: Response):
    """Redeems a one-time invite link sent via /students/{sid}/send-portal-invite.
    Logs the student in immediately (same as clicking through any other
    single-use auth link) and tells the frontend whether they still need to
    set a password — true the first time, false on a re-sent invite after
    they already have one."""
    rec = await db.student_invites.find_one({"token": body.token})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired invite link")
    if rec.get("used"):
        raise HTTPException(status_code=400, detail="This invite link has already been used")
    expires_at = rec.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if not expires_at or expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This invite link has expired — ask your teacher to resend it")
    student = await db.students.find_one({
        "_id": ObjectId(rec["student_id"]), "owner_id": rec["owner_id"],
    })
    if not student or student.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Student account not found")
    await db.student_invites.update_one(
        {"_id": rec["_id"]}, {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}}
    )
    sid = str(student["_id"])
    access = create_student_access_token(sid, rec["owner_id"])
    refresh = create_student_refresh_token(sid, rec["owner_id"])
    set_student_auth_cookies(response, access, refresh)
    return {
        "id": sid, "name": student.get("name"), "token": access,
        "must_set_password": not bool(student.get("password_hash")),
    }

@api_router.post("/student/auth/set-password")
async def student_set_password(body: StudentSetPasswordRequest, student: dict = Depends(get_current_student)):
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    await db.students.update_one(
        {"_id": ObjectId(student["_id"])}, {"$set": {"password_hash": hash_password(body.password)}}
    )
    return {"ok": True}

@api_router.post("/student/auth/change-password")
async def student_change_password(body: StudentChangePasswordRequest, student: dict = Depends(get_current_student)):
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    full = await db.students.find_one({"_id": ObjectId(student["_id"])})
    if not full or not full.get("password_hash") or not verify_password(body.current_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    await db.students.update_one(
        {"_id": ObjectId(student["_id"])},
        {"$set": {"password_hash": hash_password(body.new_password)}}
    )
    return {"ok": True}

@api_router.post("/student/auth/login")
async def student_login(body: StudentLoginRequest, response: Response):
    email = body.email.lower().strip()
    async for s in db.students.find({"email": email, "is_active": {"$ne": False}}):
        if s.get("password_hash") and verify_password(body.password, s["password_hash"]):
            sid = str(s["_id"])
            access = create_student_access_token(sid, s["owner_id"])
            refresh = create_student_refresh_token(sid, s["owner_id"])
            set_student_auth_cookies(response, access, refresh)
            return {"id": sid, "name": s.get("name"), "token": access}
    raise HTTPException(status_code=401, detail="Invalid email or password")

@api_router.post("/student/auth/refresh")
async def student_refresh(request: Request, response: Response):
    token = request.cookies.get("student_refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="No refresh token")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "student_refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")
        student = await db.students.find_one({
            "_id": ObjectId(payload["sub"]), "owner_id": payload["owner_id"],
        })
        if not student or student.get("is_active") is False:
            raise HTTPException(status_code=401, detail="Student not found")
        access = create_student_access_token(str(student["_id"]), payload["owner_id"])
        response.set_cookie("student_access_token", access, httponly=True, secure=True,
                            samesite="none", max_age=8 * 3600, path="/")
        return {"ok": True}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

@api_router.post("/student/auth/logout")
async def student_logout(response: Response, student: dict = Depends(get_current_student)):
    response.delete_cookie("student_access_token", path="/", secure=True, samesite="none")
    response.delete_cookie("student_refresh_token", path="/", secure=True, samesite="none")
    return {"ok": True}

# --------------- Student-facing data -----------------
@api_router.get("/student/me")
async def student_me(student: dict = Depends(get_current_student)):
    owner = await db.users.find_one({"_id": ObjectId(student["owner_id"])})
    return {
        "id": student["_id"],
        "name": student.get("name"),
        "email": student.get("email"),
        "level": student.get("level"),
        "photo_path": student.get("photo_path"),
        "has_password": student.get("_has_password", False),
        "studio_name": (owner or {}).get("studio_name"),
        "teacher_name": (owner or {}).get("teacher_name") or (owner or {}).get("name"),
        "contact_email": (owner or {}).get("contact_email") or (owner or {}).get("email"),
        "contact_phone": (owner or {}).get("contact_phone"),
        "outreach_access": student.get("outreach_access", False),
        "classes_suspended": bool((owner or {}).get("classes_suspended")),
    }

@api_router.patch("/student/me")
async def update_own_profile(body: StudentSelfUpdate, student: dict = Depends(get_current_student)):
    # Deliberately narrow — only the photo is self-editable. Name/email/level
    # stay teacher-managed roster fields, not something a student can change
    # unilaterally.
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    await db.students.update_one({"_id": ObjectId(student["_id"])}, {"$set": updates})
    return {"ok": True}

@api_router.post("/student/me/photo")
async def upload_own_photo(file: UploadFile = File(...), student: dict = Depends(get_current_student)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads allowed")
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    path = f"{APP_NAME}/uploads/{student['owner_id']}/student-{student['_id']}/{uuid.uuid4()}.{ext}"
    data = await file.read()
    result = put_object(path, data, file.content_type)
    await db.files.insert_one({
        "storage_path": result["path"],
        "student_id": student["_id"],
        "content_type": file.content_type,
        "size": result.get("size"),
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    await db.students.update_one({"_id": ObjectId(student["_id"])}, {"$set": {"photo_path": result["path"]}})
    return {"path": result["path"]}

def _next_occurrence_datetime(day_of_week: int, start_time: str, now_ist: datetime) -> datetime:
    """Next strictly-future occurrence of a weekly day/time, as an IST-aware
    datetime — unlike _next_occurrence() (date-only), this rolls over to next
    week when today's own slot has already started/passed."""
    today = now_ist.date()
    days_ahead = (day_of_week - today.weekday()) % 7
    candidate_date = today + timedelta(days=days_ahead)
    h, m = start_time.split(":")
    candidate_dt = datetime.combine(candidate_date, datetime.min.time(), tzinfo=IST).replace(
        hour=int(h), minute=int(m),
    )
    if candidate_dt <= now_ist:
        candidate_dt += timedelta(days=7)
    return candidate_dt

async def _owner_classes_suspended(owner_id: str) -> bool:
    owner = await db.users.find_one({"_id": ObjectId(owner_id)}, {"classes_suspended": 1})
    return bool(owner and owner.get("classes_suspended"))

@api_router.get("/student/schedule")
async def student_schedule(student: dict = Depends(get_current_student)):
    if await _owner_classes_suspended(student["owner_id"]):
        return []
    await _prune_expired_one_offs(student["owner_id"])
    now_ist = datetime.now(IST)
    out = []
    cur = db.schedule_blocks.find({
        "owner_id": student["owner_id"], "student_ids": student["_id"],
    }).sort("start_time", 1)
    async for b in cur:
        occ_dt = _next_occurrence_datetime(b["day_of_week"], b["start_time"], now_ist)
        occurs_on = occ_dt.date().isoformat()
        skipped = await db.schedule_skips.find_one({
            "block_id": str(b["_id"]), "occurs_on": occurs_on, "student_id": student["_id"],
        })
        if skipped:
            continue
        out.append(ser_schedule_block_for_student(b, occurs_on, occ_dt.isoformat()))
    return out

@api_router.get("/student/calendar")
async def student_calendar(start: str = Query(...), end: str = Query(...), student: dict = Depends(get_current_student)):
    """Dated view of this student's own upcoming classes, read-only — the
    same class_occurrences a student is on, materialized ahead by the
    teacher's schedule. No personal-events layer or clash detection here;
    those are Lakshmi-only."""
    if await _owner_classes_suspended(student["owner_id"]):
        return []
    await _top_up_occurrences(student["owner_id"])
    cur = db.class_occurrences.find({
        "owner_id": student["owner_id"], "student_ids": student["_id"],
        "date": {"$gte": start, "$lte": end}, "status": "scheduled",
    }).sort([("date", 1), ("start_time", 1)])
    out = []
    async for occ in cur:
        out.append(ser_occurrence_for_student(occ))
    return out

@api_router.get("/student/dues")
async def student_dues(student: dict = Depends(get_current_student)):
    summary = await compute_student_summary(student["owner_id"], student["_id"])
    outstanding = await _outstanding_classes(student["owner_id"], student["_id"])
    return {"summary": summary, "outstanding_classes": [c for c in outstanding if c["outstanding"] > 0]}

@api_router.get("/student/progress")
async def student_progress(student: dict = Depends(get_current_student)):
    cur = db.classes.find({
        "owner_id": student["owner_id"], "student_id": student["_id"],
    }).sort("class_date", -1)
    out = []
    async for c in cur:
        out.append({
            "id": str(c["_id"]),
            "class_date": c.get("class_date"),
            "hours": c.get("hours"),
            "topics": c.get("topics", []),
            "notes": c.get("notes"),
            "has_audio": bool(c.get("audio_path")),
            "audio_duration_seconds": c.get("audio_duration_seconds"),
            "transcript": c.get("transcript"),
        })
    return out

@api_router.get("/student/classes/{cid}/audio")
async def get_student_class_audio(cid: str, student: dict = Depends(get_current_student)):
    existing = await db.classes.find_one({
        "_id": ObjectId(cid), "owner_id": student["owner_id"], "student_id": student["_id"],
    })
    if not existing or not existing.get("audio_path"):
        raise HTTPException(status_code=404, detail="No recording on file")
    try:
        data, ct = get_object(existing["audio_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="Recording unavailable")
    return Response(content=data, media_type=ct or "audio/webm")

@api_router.get("/student/progress-monthly")
async def student_progress_monthly(months: int = 6, student: dict = Depends(get_current_student)):
    # Same month-bucketing approach as /stats/monthly, scoped to this student.
    now = datetime.now(timezone.utc).replace(day=1)
    month_keys = []
    y, m = now.year, now.month
    for _ in range(months):
        month_keys.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    month_keys.reverse()

    classes_count = {k: 0 for k in month_keys}
    hours = {k: 0.0 for k in month_keys}
    async for c in db.classes.find({"owner_id": student["owner_id"], "student_id": student["_id"]}):
        d = c.get("class_date") or ""
        key = d[:7] if len(d) >= 7 else None
        if key in classes_count:
            classes_count[key] += 1
            hours[key] += float(c.get("hours", 0))

    return {
        "months": month_keys,
        "series": [
            {"month": k, "classes": classes_count[k], "hours": round(hours[k], 2)}
            for k in month_keys
        ],
    }

# --------------- Student notes (private — never exposed to the teacher) -----------------
@api_router.get("/student/notes")
async def list_student_notes(student: dict = Depends(get_current_student)):
    cur = db.student_notes.find({"student_id": student["_id"]}).sort("created_at", -1)
    out = []
    async for d in cur:
        out.append(ser_student_note(d))
    return out

@api_router.post("/student/notes")
async def create_student_note(body: StudentNoteCreate, student: dict = Depends(get_current_student)):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Note can't be empty")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "owner_id": student["owner_id"], "student_id": student["_id"],
        "text": body.text, "created_at": now, "updated_at": now,
    }
    res = await db.student_notes.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_student_note(doc)

@api_router.patch("/student/notes/{note_id}")
async def update_student_note(note_id: str, body: StudentNoteUpdate, student: dict = Depends(get_current_student)):
    existing = await db.student_notes.find_one({"_id": ObjectId(note_id), "student_id": student["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Note not found")
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Note can't be empty")
    await db.student_notes.update_one(
        {"_id": existing["_id"]},
        {"$set": {"text": body.text, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    doc = await db.student_notes.find_one({"_id": existing["_id"]})
    return ser_student_note(doc)

@api_router.delete("/student/notes/{note_id}")
async def delete_student_note(note_id: str, student: dict = Depends(get_current_student)):
    res = await db.student_notes.delete_one({"_id": ObjectId(note_id), "student_id": student["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True}

# --------------- Change requests (cancel / reschedule) -----------------
async def _has_overlap(owner_id: str, day_of_week: int, start_time: str, end_time: str,
                        exclude_block_id: Optional[str] = None) -> bool:
    """Checks a requested weekly day/time against the recurring master
    pattern — used for permanent-scope reschedules, which change the
    schedule_blocks series itself."""
    start_m = _time_to_minutes(start_time)
    end_m = _time_to_minutes(end_time)
    async for b in db.schedule_blocks.find({"owner_id": owner_id, "day_of_week": day_of_week}):
        if exclude_block_id and str(b["_id"]) == exclude_block_id:
            continue
        if _blocks_overlap(start_m, end_m, _time_to_minutes(b["start_time"]), _time_to_minutes(b["end_time"])):
            return True
    return False

async def _has_dated_clash(owner_id: str, d_str: str, start_time: str, end_time: str,
                            exclude_occurrence_id: Optional[str] = None) -> bool:
    """Checks a requested date/time against both dated class occurrences and
    Lakshmi's personal events — used for one_time-scope reschedules, which
    only ever affect a single dated occurrence, never the recurring
    pattern."""
    if await _occurrences_overlap(owner_id, d_str, start_time, end_time, exclude_occurrence_id):
        return True
    return await _personal_events_overlap(owner_id, d_str, start_time, end_time)

@api_router.post("/student/change-requests")
async def create_change_request(body: ChangeRequestCreate, student: dict = Depends(get_current_student)):
    if await _owner_classes_suspended(student["owner_id"]):
        raise HTTPException(status_code=400, detail="Classes are currently paused — there's nothing to reschedule right now")
    if body.type not in CHANGE_REQUEST_TYPES:
        raise HTTPException(status_code=400, detail="type must be 'cancel' or 'reschedule'")
    if body.scope not in CHANGE_REQUEST_SCOPES:
        raise HTTPException(status_code=400, detail="scope must be 'one_time' or 'permanent'")
    block = await db.schedule_blocks.find_one({
        "_id": ObjectId(body.block_id), "owner_id": student["owner_id"], "student_ids": student["_id"],
    })
    if not block:
        raise HTTPException(status_code=404, detail="Class not found")

    existing_pending = await db.schedule_change_requests.find_one({
        "student_id": student["_id"], "block_id": body.block_id, "status": "pending",
    })
    if existing_pending:
        raise HTTPException(
            status_code=409,
            detail="You already have a pending request for this class — wait for your teacher to respond before sending another.",
        )

    now_ist = datetime.now(IST)
    occ_dt = _next_occurrence_datetime(block["day_of_week"], block["start_time"], now_ist)
    if occ_dt - now_ist < timedelta(hours=24):
        raise HTTPException(status_code=422, detail="Changes must be requested at least 24 hours before the class")

    doc = {
        "owner_id": student["owner_id"],
        "student_id": student["_id"],
        "block_id": body.block_id,
        "occurs_on": occ_dt.date().isoformat(),
        "type": body.type,
        "scope": body.scope,
        "requested_day_of_week": body.requested_day_of_week,
        "requested_start_time": body.requested_start_time,
        "requested_end_time": body.requested_end_time,
        "reason": body.reason,
        "status": "pending",
        "auto_denied": False,
        "denial_reason": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decided_at": None,
    }

    if body.type == "reschedule":
        if body.requested_day_of_week is None or not body.requested_start_time or not body.requested_end_time:
            raise HTTPException(status_code=400, detail="A reschedule needs a requested day, start time and end time")
        if not (0 <= body.requested_day_of_week <= 6):
            raise HTTPException(status_code=400, detail="requested_day_of_week must be 0-6")
        if _time_to_minutes(body.requested_end_time) <= _time_to_minutes(body.requested_start_time):
            raise HTTPException(status_code=400, detail="requested end time must be after the start time")
        if body.scope == "permanent":
            clash = await _has_overlap(
                student["owner_id"], body.requested_day_of_week, body.requested_start_time, body.requested_end_time,
                exclude_block_id=body.block_id,
            )
        else:
            requested_dt = _next_occurrence_datetime(body.requested_day_of_week, body.requested_start_time, now_ist)
            clash = await _has_dated_clash(
                student["owner_id"], requested_dt.date().isoformat(),
                body.requested_start_time, body.requested_end_time,
            )
        if clash:
            # Auto-deny — a time that's already taken never reaches the
            # teacher for a decision.
            doc["status"] = "denied"
            doc["auto_denied"] = True
            doc["denial_reason"] = "That time overlaps an existing class on your teacher's schedule."
            doc["decided_at"] = datetime.now(timezone.utc).isoformat()

    res = await db.schedule_change_requests.insert_one(doc)
    doc["_id"] = res.inserted_id

    kind = "cancel" if doc["type"] == "cancel" else "reschedule"
    if doc["status"] == "pending":
        owner = await db.users.find_one({"_id": ObjectId(student["owner_id"])})
        teacher_email = (owner or {}).get("contact_email") or (owner or {}).get("email")
        if teacher_email:
            app_url = (os.environ.get("APP_URL") or "").rstrip("/")
            review_link = f"{app_url}/requests" if app_url else ""
            await email_service.send_change_request_email(
                teacher_email, student.get("name") or "A student", doc, review_link,
            )
        await push_service.send_push(
            "user", student["owner_id"],
            "New request", f"{student.get('name') or 'A student'} asked to {kind} a class",
            "/requests",
        )
    else:
        # Auto-denied — nothing for the teacher to do, but the student should
        # still hear back immediately rather than only seeing it in the app.
        await push_service.send_push(
            "student", student["_id"],
            "Request not available", doc["denial_reason"] or "That time isn't available",
            "/portal/schedule",
        )

    return ser_change_request(doc)

@api_router.get("/student/change-requests")
async def list_own_change_requests(student: dict = Depends(get_current_student)):
    cur = db.schedule_change_requests.find({"student_id": student["_id"]}).sort("created_at", -1)
    out = []
    async for d in cur:
        out.append(ser_change_request(d))
    return out

# --------------- Payment proof uploads -----------------
@api_router.post("/student/payment-proofs")
async def upload_payment_proof(file: UploadFile = File(...), amount_claimed: Optional[float] = Form(None),
                                note: Optional[str] = Form(None), student: dict = Depends(get_current_student)):
    if not file.content_type or file.content_type not in PAYMENT_PROOF_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP or PDF files are allowed")
    data = await file.read()
    if len(data) > PAYMENT_PROOF_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 10MB)")
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    path = f"{APP_NAME}/payment-proofs/{student['owner_id']}/{student['_id']}/{uuid.uuid4()}.{ext}"
    result = put_object(path, data, file.content_type)
    doc = {
        "owner_id": student["owner_id"],
        "student_id": student["_id"],
        "storage_path": result["path"],
        "content_type": file.content_type,
        "amount_claimed": amount_claimed,
        "note": note,
        "status": "pending",
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.payment_proofs.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_payment_proof(doc)

@api_router.get("/student/payment-proofs")
async def list_own_payment_proofs(student: dict = Depends(get_current_student)):
    cur = db.payment_proofs.find({"student_id": student["_id"]}).sort("uploaded_at", -1)
    out = []
    async for d in cur:
        out.append(ser_payment_proof(d))
    return out

@api_router.get("/student/payment-proofs/{proof_id}/file")
async def get_own_payment_proof_file(proof_id: str, student: dict = Depends(get_current_student)):
    rec = await db.payment_proofs.find_one({"_id": ObjectId(proof_id), "student_id": student["_id"]})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct))

# --------------- Teacher-facing review queues -----------------
async def _remove_student_from_block(owner_id: str, block: dict, student_id: str):
    remaining = [sid for sid in block.get("student_ids", []) if sid != student_id]
    if remaining:
        await db.schedule_blocks.update_one({"_id": block["_id"]}, {"$set": {"student_ids": remaining}})
        updated = await db.schedule_blocks.find_one({"_id": block["_id"]})
        names = await _student_names(owner_id, remaining)
        event_id = await calendar_service.sync_block_upsert(owner_id, updated, names)
        if event_id and event_id != updated.get("google_event_id"):
            await db.schedule_blocks.update_one({"_id": block["_id"]}, {"$set": {"google_event_id": event_id}})
        await _regenerate_block_occurrences(owner_id, updated)
    else:
        await calendar_service.sync_block_delete(owner_id, block.get("google_event_id"))
        await db.schedule_blocks.delete_one({"_id": block["_id"]})
        today_str = date.today().isoformat()
        await db.class_occurrences.delete_many({
            "block_id": str(block["_id"]), "date": {"$gte": today_str},
            "status": "scheduled", "origin": "recurring",
        })

async def _find_requested_occurrence(owner_id: str, req: dict) -> Optional[dict]:
    """Locates the specific dated class_occurrences document a one_time
    change request refers to — matched on the block it came from, the date
    the student was asked about, and the student being on it. Falls back to
    generating it on the fly if the rolling horizon job hasn't materialized
    that far out yet (shouldn't normally happen within the 24h+ notice
    window, but a request made right at the edge of the horizon could)."""
    occ = await db.class_occurrences.find_one({
        "owner_id": owner_id, "block_id": req["block_id"], "date": req["occurs_on"],
        "student_ids": req["student_id"],
    })
    if occ:
        return occ
    block = await db.schedule_blocks.find_one({"_id": ObjectId(req["block_id"]), "owner_id": owner_id})
    if not block:
        return None
    await _generate_occurrences_for_block(owner_id, block)
    return await db.class_occurrences.find_one({
        "owner_id": owner_id, "block_id": req["block_id"], "date": req["occurs_on"],
        "student_ids": req["student_id"],
    })

@api_router.get("/change-requests")
async def list_change_requests(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"owner_id": user["_id"]}
    if status:
        q["status"] = status
    cur = db.schedule_change_requests.find(q).sort("created_at", -1)
    out = []
    async for d in cur:
        item = ser_change_request(d)
        s = await db.students.find_one({"_id": ObjectId(d["student_id"])})
        item["student_name"] = (s or {}).get("name")
        out.append(item)
    return out

@api_router.post("/change-requests/{request_id}/approve")
async def approve_change_request(request_id: str, user: dict = Depends(get_current_user)):
    req = await db.schedule_change_requests.find_one({"_id": ObjectId(request_id), "owner_id": user["_id"]})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="This request has already been decided")
    block = await db.schedule_blocks.find_one({"_id": ObjectId(req["block_id"]), "owner_id": user["_id"]})
    if not block:
        raise HTTPException(status_code=404, detail="The original class no longer exists")

    if req["type"] == "reschedule" and req["scope"] == "permanent":
        clash = await _has_overlap(
            user["_id"], req["requested_day_of_week"], req["requested_start_time"], req["requested_end_time"],
            exclude_block_id=req["block_id"],
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail="That time now overlaps another class — deny this request or ask the student for a different time",
            )
    elif req["type"] == "reschedule" and req["scope"] == "one_time":
        requested_dt = _next_occurrence_datetime(
            req["requested_day_of_week"], req["requested_start_time"], datetime.now(IST),
        )
        clash = await _has_dated_clash(
            user["_id"], requested_dt.date().isoformat(), req["requested_start_time"], req["requested_end_time"],
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail="That time now clashes with another class or a personal event — deny this request or ask the student for a different time",
            )

    if req["scope"] == "one_time":
        # Only this one dated occurrence changes — the recurring
        # schedule_blocks pattern (and every other student on a shared
        # block) is untouched. A student sharing the slot with others just
        # gets removed from this single date's student list rather than the
        # whole occurrence being cancelled/moved out from under them.
        occ = await _find_requested_occurrence(user["_id"], req)
        if not occ:
            raise HTTPException(status_code=404, detail="The original class occurrence no longer exists")
        other_students = [sid for sid in occ.get("student_ids", []) if sid != req["student_id"]]
        if other_students:
            # Split: this student peels off into their own detached
            # occurrence (cancelled, or moved to the new date/time); everyone
            # else keeps the original occurrence untouched.
            await db.class_occurrences.update_one(
                {"_id": occ["_id"]}, {"$set": {"student_ids": other_students}},
            )
            if req["type"] == "cancel":
                await db.class_occurrences.insert_one({
                    "owner_id": user["_id"], "block_id": occ["block_id"], "date": occ["date"],
                    "start_time": occ["start_time"], "end_time": occ["end_time"],
                    "student_ids": [req["student_id"]], "notes": occ.get("notes"),
                    "status": "cancelled", "origin": "recurring", "moved_from_date": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            else:
                await db.class_occurrences.insert_one({
                    "owner_id": user["_id"], "block_id": occ["block_id"],
                    "date": requested_dt.date().isoformat(),
                    "start_time": req["requested_start_time"], "end_time": req["requested_end_time"],
                    "student_ids": [req["student_id"]], "notes": f"Rescheduled from {occ['date']} (student request)",
                    "status": "scheduled", "origin": "rescheduled", "moved_from_date": occ["date"],
                    "moved_from_start_time": occ["start_time"], "moved_from_end_time": occ["end_time"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
        elif req["type"] == "cancel":
            await db.class_occurrences.update_one({"_id": occ["_id"]}, {"$set": {"status": "cancelled"}})
        else:
            await db.class_occurrences.update_one(
                {"_id": occ["_id"]},
                {"$set": {
                    "date": requested_dt.date().isoformat(),
                    "start_time": req["requested_start_time"], "end_time": req["requested_end_time"],
                    "origin": "rescheduled", "moved_from_date": occ["date"],
                    "moved_from_start_time": occ["start_time"], "moved_from_end_time": occ["end_time"],
                }},
            )
    elif req["type"] == "cancel" and req["scope"] == "permanent":
        await _remove_student_from_block(user["_id"], block, req["student_id"])
    elif req["type"] == "reschedule" and req["scope"] == "permanent":
        await _remove_student_from_block(user["_id"], block, req["student_id"])
        new_block = {
            "owner_id": user["_id"],
            "day_of_week": req["requested_day_of_week"],
            "start_time": req["requested_start_time"],
            "end_time": req["requested_end_time"],
            "student_ids": [req["student_id"]],
            "notes": None,
            "is_one_off": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        res = await db.schedule_blocks.insert_one(new_block)
        new_block["_id"] = res.inserted_id
        names = await _student_names(user["_id"], new_block["student_ids"])
        event_id = await calendar_service.sync_block_upsert(user["_id"], new_block, names)
        if event_id:
            await db.schedule_blocks.update_one({"_id": new_block["_id"]}, {"$set": {"google_event_id": event_id}})
        await _generate_occurrences_for_block(user["_id"], new_block)

    await db.schedule_change_requests.update_one(
        {"_id": req["_id"]},
        {"$set": {"status": "approved", "decided_at": datetime.now(timezone.utc).isoformat()}},
    )
    kind = "cancel" if req["type"] == "cancel" else "reschedule"
    await push_service.send_push(
        "student", req["student_id"],
        "Request approved", f"Your {kind} request was approved", "/portal/schedule",
    )
    updated = await db.schedule_change_requests.find_one({"_id": req["_id"]})
    return ser_change_request(updated)

@api_router.post("/change-requests/{request_id}/deny")
async def deny_change_request(request_id: str, body: ChangeRequestDeny, user: dict = Depends(get_current_user)):
    req = await db.schedule_change_requests.find_one({"_id": ObjectId(request_id), "owner_id": user["_id"]})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req["status"] != "pending":
        raise HTTPException(status_code=400, detail="This request has already been decided")
    await db.schedule_change_requests.update_one(
        {"_id": req["_id"]},
        {"$set": {"status": "denied", "denial_reason": body.reason,
                  "decided_at": datetime.now(timezone.utc).isoformat()}},
    )
    kind = "cancel" if req["type"] == "cancel" else "reschedule"
    push_body = f"Your {kind} request was denied" + (f": {body.reason}" if body.reason else "")
    await push_service.send_push("student", req["student_id"], "Request denied", push_body, "/portal/schedule")
    updated = await db.schedule_change_requests.find_one({"_id": req["_id"]})
    return ser_change_request(updated)

@api_router.get("/payment-proofs")
async def list_payment_proofs(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    q = {"owner_id": user["_id"]}
    if status:
        q["status"] = status
    cur = db.payment_proofs.find(q).sort("uploaded_at", -1)
    out = []
    async for d in cur:
        item = ser_payment_proof(d)
        s = await db.students.find_one({"_id": ObjectId(d["student_id"])})
        item["student_name"] = (s or {}).get("name")
        out.append(item)
    return out

@api_router.post("/payment-proofs/{proof_id}/mark-reviewed")
async def mark_payment_proof_reviewed(proof_id: str, user: dict = Depends(get_current_user)):
    res = await db.payment_proofs.update_one(
        {"_id": ObjectId(proof_id), "owner_id": user["_id"]},
        {"$set": {"status": "reviewed", "reviewed_at": datetime.now(timezone.utc).isoformat()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    doc = await db.payment_proofs.find_one({"_id": ObjectId(proof_id)})
    return ser_payment_proof(doc)

@api_router.get("/payment-proofs/{proof_id}/file")
async def get_payment_proof_file(proof_id: str, user: dict = Depends(get_current_user)):
    rec = await db.payment_proofs.find_one({"_id": ObjectId(proof_id), "owner_id": user["_id"]})
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type", ct))

# --------------- Push notifications (change-request events) -----------------
class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class PushSubscribeRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys

class PushUnsubscribeRequest(BaseModel):
    endpoint: str

async def _save_push_subscription(owner_type: str, owner_id: str, body: PushSubscribeRequest):
    await db.push_subscriptions.update_one(
        {"endpoint": body.endpoint},
        {"$set": {
            "owner_type": owner_type,
            "owner_id": owner_id,
            "endpoint": body.endpoint,
            "keys": body.keys.model_dump(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )

@api_router.post("/push/subscribe")
async def push_subscribe(body: PushSubscribeRequest, user: dict = Depends(get_current_user)):
    await _save_push_subscription("user", user["_id"], body)
    return {"ok": True}

@api_router.post("/push/unsubscribe")
async def push_unsubscribe(body: PushUnsubscribeRequest, user: dict = Depends(get_current_user)):
    await db.push_subscriptions.delete_one({"endpoint": body.endpoint, "owner_type": "user", "owner_id": user["_id"]})
    return {"ok": True}

@api_router.post("/student/push/subscribe")
async def student_push_subscribe(body: PushSubscribeRequest, student: dict = Depends(get_current_student)):
    await _save_push_subscription("student", student["_id"], body)
    return {"ok": True}

@api_router.post("/student/push/unsubscribe")
async def student_push_unsubscribe(body: PushUnsubscribeRequest, student: dict = Depends(get_current_student)):
    await db.push_subscriptions.delete_one({"endpoint": body.endpoint, "owner_type": "student", "owner_id": student["_id"]})
    return {"ok": True}

# --------------- Google Calendar OAuth -----------------
@api_router.get("/calendar/status")
async def calendar_status(user: dict = Depends(get_current_user)):
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    has_token = bool(full and full.get("google_refresh_token"))
    # A stored refresh token isn't proof the connection still works — Google
    # can expire/revoke it independently of anything happening in this app.
    # Actually attempt a refresh (full SCOPES: Calendar + Drive, the same
    # backup relies on) so "Connected" here means "would work right now",
    # not just "we still have a token saved from whenever she last connected".
    working = False
    if has_token:
        creds = await calendar_service.get_credentials(user["_id"], scopes=calendar_service.SCOPES)
        working = creds is not None
    return {
        "configured": calendar_service.is_configured(),
        "connected": working,
        "needs_reconnect": has_token and not working,
        "calendar_name": (full or {}).get("google_calendar_name") or calendar_service.DEFAULT_CALENDAR_NAME,
    }

@api_router.patch("/calendar/name")
async def calendar_set_name(body: CalendarNameUpdate, user: dict = Depends(get_current_user)):
    name = body.calendar_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Calendar name can't be empty")
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    if full and full.get("google_refresh_token"):
        raise HTTPException(status_code=400, detail="Disconnect before renaming — the connected calendar keeps its current name")
    await db.users.update_one({"_id": ObjectId(user["_id"])}, {"$set": {"google_calendar_name": name}})
    return {"calendar_name": name}

@api_router.get("/calendar/connect")
async def calendar_connect(user: dict = Depends(get_current_user)):
    if not calendar_service.is_configured():
        raise HTTPException(status_code=400, detail="Google Calendar is not configured on this server")
    # state carries the owner id through Google's redirect so the callback
    # (which Google calls directly, no auth cookie of ours) knows who connected.
    url = calendar_service.build_auth_url(state=user["_id"])
    return {"url": url}

@api_router.get("/calendar/oauth/callback")
async def calendar_oauth_callback(code: str, state: str):
    await calendar_service.handle_oauth_callback(owner_id=state, code=code)
    app_url = os.environ.get("APP_URL", "/")
    return RedirectResponse(url=f"{app_url}/settings?calendar=connected")

@api_router.post("/calendar/disconnect")
async def calendar_disconnect(user: dict = Depends(get_current_user)):
    await calendar_service.disconnect(user["_id"])
    return {"ok": True}

# --------------- Tours endpoints -----------------
async def _get_owned_tour(tour_id: str, owner_id: str) -> dict:
    tour = await db.tours.find_one({"_id": ObjectId(tour_id), "owner_id": owner_id})
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    return tour

@api_router.get("/tours")
async def list_tours(user: dict = Depends(get_current_user)):
    cur = db.tours.find({"owner_id": user["_id"]}).sort("start_date", -1)
    return [ser_tour(d) async for d in cur]

@api_router.post("/tours")
async def create_tour(body: TourCreate, user: dict = Depends(get_current_user)):
    doc = body.model_dump()
    doc["owner_id"] = user["_id"]
    doc["share_token"] = secrets.token_urlsafe(24)
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.tours.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour(doc)

@api_router.get("/tours/{tour_id}")
async def get_tour(tour_id: str, user: dict = Depends(get_current_user)):
    return ser_tour(await _get_owned_tour(tour_id, user["_id"]))

@api_router.patch("/tours/{tour_id}")
async def update_tour(tour_id: str, body: TourUpdate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "custom_slug" in updates:
        slug = updates["custom_slug"].strip().lower()
        if not slug:
            updates["custom_slug"] = None  # explicit "" clears back to the random share link
        else:
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]", slug):
                raise HTTPException(status_code=400,
                    detail="Custom link can only contain lowercase letters, numbers, and hyphens (3-50 characters)")
            if slug in RESERVED_SLUGS:
                raise HTTPException(status_code=400, detail=f'"{slug}" is reserved and can\'t be used')
            existing = await db.tours.find_one({"custom_slug": slug, "_id": {"$ne": ObjectId(tour_id)}})
            if existing:
                raise HTTPException(status_code=409, detail="That custom link is already taken by another tour")
            updates["custom_slug"] = slug
    await db.tours.update_one({"_id": ObjectId(tour_id)}, {"$set": updates})
    return ser_tour(await db.tours.find_one({"_id": ObjectId(tour_id)}))

@api_router.delete("/tours/{tour_id}")
async def delete_tour(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    await db.tours.delete_one({"_id": ObjectId(tour_id)})
    await db.tour_stops.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    await db.tour_expenses.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    await db.tour_checkins.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    await db.tour_contacts.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    await db.tour_todos.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    await db.tour_invoices.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    await db.tour_files.delete_many({"tour_id": tour_id, "owner_id": user["_id"]})
    return {"ok": True}

# --------------- Tour stops (schedule) -----------------
@api_router.get("/tours/{tour_id}/stops")
async def list_tour_stops(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_stops.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("stop_date", 1)
    return [ser_tour_stop(d) async for d in cur]

@api_router.post("/tours/{tour_id}/stops")
async def create_tour_stop(tour_id: str, body: TourStopCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    doc = body.model_dump()
    doc["tour_id"] = tour_id
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    # Best-effort — a stop always saves even if the venue name doesn't
    # geocode cleanly; she can retry by editing once it's fixed.
    geo = await geocoding_service.geocode_venue(body.venue, body.city)
    if geo:
        doc.update(geo)
    res = await db.tour_stops.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_stop(doc)

@api_router.patch("/tours/{tour_id}/stops/{stop_id}")
async def update_tour_stop(tour_id: str, stop_id: str, body: TourStopUpdate,
                            user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    existing = await db.tour_stops.find_one({"_id": ObjectId(stop_id), "tour_id": tour_id, "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Stop not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    # Only re-geocode if the venue or city actually changed — avoids an
    # unnecessary Nominatim call (and possibly clobbering a good pin) on
    # every unrelated edit like notes or time.
    if "venue" in updates or "city" in updates:
        venue = updates.get("venue", existing.get("venue"))
        city = updates.get("city", existing.get("city"))
        geo = await geocoding_service.geocode_venue(venue, city)
        if geo:
            updates.update(geo)
        else:
            # The old pin describes the previous venue text, not this one —
            # leaving it in place would silently mislead (wrong location
            # shown as if it were confirmed for the new venue).
            updates["latitude"] = None
            updates["longitude"] = None
            updates["formatted_address"] = None
    res = await db.tour_stops.update_one(
        {"_id": ObjectId(stop_id), "tour_id": tour_id, "owner_id": user["_id"]}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Stop not found")
    return ser_tour_stop(await db.tour_stops.find_one({"_id": ObjectId(stop_id)}))

@api_router.delete("/tours/{tour_id}/stops/{stop_id}")
async def delete_tour_stop(tour_id: str, stop_id: str, user: dict = Depends(get_current_user)):
    res = await db.tour_stops.delete_one(
        {"_id": ObjectId(stop_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Stop not found")
    return {"ok": True}

# --------------- Tour expenses -----------------
@api_router.get("/tours/{tour_id}/expenses")
async def list_tour_expenses(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_expenses.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("expense_date", -1)
    return [ser_tour_expense(d) async for d in cur]

@api_router.post("/tours/{tour_id}/expenses")
async def create_tour_expense(tour_id: str, body: TourExpenseCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    if body.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    doc = body.model_dump()
    doc["tour_id"] = tour_id
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.tour_expenses.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_expense(doc)

@api_router.patch("/tours/{tour_id}/expenses/{expense_id}")
async def update_tour_expense(tour_id: str, expense_id: str, body: TourExpenseUpdate,
                               user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "currency" in updates and updates["currency"] not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    res = await db.tour_expenses.update_one(
        {"_id": ObjectId(expense_id), "tour_id": tour_id, "owner_id": user["_id"]}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    return ser_tour_expense(await db.tour_expenses.find_one({"_id": ObjectId(expense_id)}))

@api_router.delete("/tours/{tour_id}/expenses/{expense_id}")
async def delete_tour_expense(tour_id: str, expense_id: str, user: dict = Depends(get_current_user)):
    res = await db.tour_expenses.delete_one(
        {"_id": ObjectId(expense_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Expense not found")
    return {"ok": True}

@api_router.get("/tours/{tour_id}/expenses/export.csv")
async def export_tour_expenses_csv(tour_id: str, user: dict = Depends(get_current_user)):
    tour = await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_expenses.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("expense_date", 1)
    expenses = [d async for d in cur]
    csv_bytes = tours_service.expenses_to_csv(tour, expenses)
    filename = f"expenses_{tour['name'].replace(' ', '_')}.csv"
    return StreamingResponse(io.BytesIO(csv_bytes), media_type="text/csv",
                              headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@api_router.get("/tours/{tour_id}/expenses/export.pdf")
async def export_tour_expenses_pdf(tour_id: str, user: dict = Depends(get_current_user)):
    tour = await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_expenses.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("expense_date", 1)
    expenses = [d async for d in cur]
    pdf_bytes = pdf_service.generate_tour_expense_pdf(tour, expenses)
    filename = f"expenses_{tour['name'].replace(' ', '_')}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                              headers={"Content-Disposition": f'attachment; filename="{filename}"'})

# --------------- Tour check-ins (GPS log) -----------------
@api_router.get("/tours/{tour_id}/checkins")
async def list_tour_checkins(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_checkins.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("created_at", -1)
    return [ser_tour_checkin(d) async for d in cur]

@api_router.post("/tours/{tour_id}/checkins")
async def create_tour_checkin(tour_id: str, body: TourCheckinCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    doc = body.model_dump()
    doc["tour_id"] = tour_id
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.tour_checkins.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_checkin(doc)

@api_router.delete("/tours/{tour_id}/checkins/{checkin_id}")
async def delete_tour_checkin(tour_id: str, checkin_id: str, user: dict = Depends(get_current_user)):
    res = await db.tour_checkins.delete_one(
        {"_id": ObjectId(checkin_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Check-in not found")
    return {"ok": True}

# --------------- Tour contacts -----------------
@api_router.get("/tours/{tour_id}/contacts")
async def list_tour_contacts(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_contacts.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("created_at", -1)
    return [ser_tour_contact(d) async for d in cur]

@api_router.post("/tours/{tour_id}/contacts")
async def create_tour_contact(tour_id: str, body: TourContactCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    doc = body.model_dump()
    doc["tour_id"] = tour_id
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.tour_contacts.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_contact(doc)

@api_router.patch("/tours/{tour_id}/contacts/{contact_id}")
async def update_tour_contact(tour_id: str, contact_id: str, body: TourContactUpdate,
                               user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.tour_contacts.update_one(
        {"_id": ObjectId(contact_id), "tour_id": tour_id, "owner_id": user["_id"]}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return ser_tour_contact(await db.tour_contacts.find_one({"_id": ObjectId(contact_id)}))

@api_router.delete("/tours/{tour_id}/contacts/{contact_id}")
async def delete_tour_contact(tour_id: str, contact_id: str, user: dict = Depends(get_current_user)):
    res = await db.tour_contacts.delete_one(
        {"_id": ObjectId(contact_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True}

# --------------- Tour files (Google Drive attachments) -----------------
# The file itself always lives in her Drive — the app only stores a
# reference (drive_file_id + display metadata) picked via the Google Picker
# widget, never the file content. See /drive/picker-token below for how the
# frontend gets a short-lived token to open the picker.
@api_router.get("/tours/{tour_id}/files")
async def list_tour_files(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_files.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("created_at", -1)
    return [ser_tour_file(d) async for d in cur]

@api_router.post("/tours/{tour_id}/files")
async def create_tour_file(tour_id: str, body: TourFileCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    doc = body.model_dump()
    doc["tour_id"] = tour_id
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.tour_files.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_file(doc)

@api_router.delete("/tours/{tour_id}/files/{file_id}")
async def delete_tour_file(tour_id: str, file_id: str, user: dict = Depends(get_current_user)):
    """Only unlinks the reference — the file itself is untouched in her
    Drive, since the app never owns it."""
    res = await db.tour_files.delete_one(
        {"_id": ObjectId(file_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="File not found")
    return {"ok": True}

@api_router.get("/drive/picker-token")
async def drive_picker_token(user: dict = Depends(get_current_user)):
    """Mints a short-lived Drive access token for the Google Picker widget
    to run client-side. Never exposes the stored refresh token — the
    frontend only ever sees this token, which expires in ~1 hour and is
    scoped to drive.file (the Picker itself further narrows this to just
    whatever file she explicitly selects)."""
    creds = await calendar_service.get_credentials(user["_id"], scopes=calendar_service.DRIVE_SCOPES)
    if not creds:
        raise HTTPException(status_code=404, detail="Google Drive not connected")
    return {"access_token": creds.token}

# --------------- Tour to-do list -----------------
@api_router.get("/tours/{tour_id}/todos")
async def list_tour_todos(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_todos.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("created_at", 1)
    return [ser_tour_todo(d) async for d in cur]

@api_router.post("/tours/{tour_id}/todos")
async def create_tour_todo(tour_id: str, body: TourTodoCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    doc = {
        "tour_id": tour_id,
        "owner_id": user["_id"],
        "text": body.text,
        "done": False,
        "due_date": body.due_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.tour_todos.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_todo(doc)

@api_router.patch("/tours/{tour_id}/todos/{todo_id}")
async def update_tour_todo(tour_id: str, todo_id: str, body: TourTodoUpdate,
                            user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    res = await db.tour_todos.update_one(
        {"_id": ObjectId(todo_id), "tour_id": tour_id, "owner_id": user["_id"]}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="To-do not found")
    return ser_tour_todo(await db.tour_todos.find_one({"_id": ObjectId(todo_id)}))

@api_router.delete("/tours/{tour_id}/todos/{todo_id}")
async def delete_tour_todo(tour_id: str, todo_id: str, user: dict = Depends(get_current_user)):
    res = await db.tour_todos.delete_one(
        {"_id": ObjectId(todo_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="To-do not found")
    return {"ok": True}

# --------------- Tour invoices -----------------
@api_router.get("/tours/{tour_id}/invoices")
async def list_tour_invoices(tour_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    cur = db.tour_invoices.find({"tour_id": tour_id, "owner_id": user["_id"]}).sort("created_at", -1)
    return [ser_tour_invoice(d) async for d in cur]

@api_router.post("/tours/{tour_id}/invoices")
async def create_tour_invoice(tour_id: str, body: TourInvoiceCreate, user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    if body.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    now = datetime.now(timezone.utc)
    doc = body.model_dump()
    doc["tour_id"] = tour_id
    doc["owner_id"] = user["_id"]
    doc["paid"] = False
    doc["share_token"] = secrets.token_urlsafe(24)
    doc["invoice_number"] = await invoices_service.next_invoice_number(user["_id"], now, namespace="tour")
    doc["created_at"] = now.isoformat()
    res = await db.tour_invoices.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_invoice(doc)

@api_router.patch("/tours/{tour_id}/invoices/{invoice_id}")
async def update_tour_invoice(tour_id: str, invoice_id: str, body: TourInvoiceUpdate,
                               user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "currency" in updates and updates["currency"] not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    res = await db.tour_invoices.update_one(
        {"_id": ObjectId(invoice_id), "tour_id": tour_id, "owner_id": user["_id"]}, {"$set": updates}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return ser_tour_invoice(await db.tour_invoices.find_one({"_id": ObjectId(invoice_id)}))

@api_router.delete("/tours/{tour_id}/invoices/{invoice_id}")
async def delete_tour_invoice(tour_id: str, invoice_id: str, user: dict = Depends(get_current_user)):
    res = await db.tour_invoices.delete_one(
        {"_id": ObjectId(invoice_id), "tour_id": tour_id, "owner_id": user["_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return {"ok": True}

async def _get_owned_tour_invoice(tour_id: str, invoice_id: str, owner_id: str) -> dict:
    inv = await db.tour_invoices.find_one(
        {"_id": ObjectId(invoice_id), "tour_id": tour_id, "owner_id": owner_id}
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv

@api_router.get("/tours/{tour_id}/invoices/{invoice_id}/pdf")
async def tour_invoice_pdf(tour_id: str, invoice_id: str, token: Optional[str] = Query(None),
                            request: Request = None):
    inv = await db.tour_invoices.find_one({"_id": ObjectId(invoice_id), "tour_id": tour_id})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if token and token == inv["share_token"]:
        pass
    else:
        try:
            user = await get_current_user(request)
            if user["_id"] != inv["owner_id"]:
                raise HTTPException(status_code=403, detail="Not authorized")
        except HTTPException:
            raise HTTPException(status_code=401, detail="Not authenticated")

    owner = await db.users.find_one({"_id": ObjectId(inv["owner_id"])})
    studio_snapshot = invoices_service.build_studio_snapshot(owner)
    logo_bytes = None
    if studio_snapshot.get("logo_path"):
        try:
            logo_bytes, _ = get_object(studio_snapshot["logo_path"])
        except Exception as e:
            logger.warning(f"Logo fetch failed for tour invoice {invoice_id}: {e}")

    pdf_bytes = pdf_service.generate_tour_invoice_pdf(
        studio_snapshot["teacher_name"] or "Dance Teacher",
        studio_snapshot.get("studio_name"),
        logo_bytes,
        ser_tour_invoice(inv),
        studio_contact=studio_snapshot,
    )
    filename = f"invoice_{invoice_id}.pdf"
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf",
                              headers={"Content-Disposition": f'inline; filename="{filename}"'})

@api_router.post("/tours/{tour_id}/invoices/{invoice_id}/send")
async def send_tour_invoice(tour_id: str, invoice_id: str, body: TourInvoiceSend,
                             user: dict = Depends(get_current_user)):
    inv = await _get_owned_tour_invoice(tour_id, invoice_id, user["_id"])
    if not inv.get("recipient_email") and "email" in body.channels:
        raise HTTPException(status_code=400, detail="No recipient email on file")

    owner = await db.users.find_one({"_id": ObjectId(user["_id"])})
    studio_snapshot = invoices_service.build_studio_snapshot(owner)
    teacher_name = studio_snapshot["teacher_name"] or "Dance Teacher"
    backend_url = os.environ.get("BACKEND_URL", "").rstrip("/")
    pdf_link = f"{backend_url}/api/tours/{tour_id}/invoices/{invoice_id}/pdf?token={inv['share_token']}"

    result = {"email": None, "whatsapp": None}

    if "email" in body.channels and inv.get("recipient_email"):
        html = email_service.build_tour_invoice_email_html(ser_tour_invoice(inv), teacher_name, pdf_link)
        payload = {
            "to": [inv["recipient_email"]],
            "subject": f"Invoice from {teacher_name}",
            "html": html,
            "from_name": teacher_name,
        }
        try:
            await email_service.dispatch_email(payload)
            result["email"] = "sent"
        except Exception as e:
            logger.error(f"Tour invoice email failed: {e}")
            result["email"] = "failed"

    if "whatsapp" in body.channels:
        phone = inv.get("recipient_phone")
        if not phone and inv.get("contact_id"):
            contact = await db.tour_contacts.find_one({"_id": ObjectId(inv["contact_id"])})
            phone = (contact or {}).get("phone")
        if phone:
            symbol = CURRENCY_SYMBOLS.get(inv["currency"], inv["currency"])
            msg = (f"Hi {inv['recipient_name']}, here's your invoice for "
                   f"{inv['description']} ({symbol}{inv['amount']}):\n{pdf_link}")
            result["whatsapp"] = invoices_service.wa_link(phone, msg)
        else:
            result["whatsapp"] = None

    await db.tour_invoices.update_one(
        {"_id": ObjectId(invoice_id)},
        {"$set": {
            "last_sent_to": inv.get("recipient_email"),
            "last_sent_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return result

# --------------- Public tour schedule page -----------------
async def _ser_shared_tour(tour: dict) -> dict:
    cur = db.tour_stops.find({"tour_id": str(tour["_id"])}).sort("stop_date", 1)
    stops = [ser_tour_stop(d) async for d in cur]
    owner = await db.users.find_one({"_id": ObjectId(tour["owner_id"])}) if tour.get("owner_id") else None
    studio = {
        "studio_name": (owner or {}).get("studio_name"),
        "teacher_name": (owner or {}).get("teacher_name") or (owner or {}).get("name"),
        "social_youtube": (owner or {}).get("social_youtube"),
        "social_instagram": (owner or {}).get("social_instagram"),
        "social_facebook": (owner or {}).get("social_facebook"),
    }
    return {
        "name": tour.get("name"),
        "start_date": tour.get("start_date"),
        "end_date": tour.get("end_date"),
        "location": tour.get("location"),
        "stops": stops,
        "studio": studio,
    }

@api_router.get("/tours/share/{share_token}")
async def get_shared_tour(share_token: str):
    tour = await db.tours.find_one({"share_token": share_token})
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    return await _ser_shared_tour(tour)

@api_router.get("/tours/slug/{slug}")
async def get_tour_by_slug(slug: str):
    """Resolves a tour's custom public link (e.g. pravaahacfm.com/tour2026)
    — same payload as the share-token lookup, just a friendlier URL."""
    tour = await db.tours.find_one({"custom_slug": slug.lower()})
    if not tour:
        raise HTTPException(status_code=404, detail="Not found")
    return await _ser_shared_tour(tour)

# --------------- Events (workshops) -----------------
async def _get_owned_event(event_id: str, owner_id: str) -> dict:
    event = await db.events.find_one({"_id": ObjectId(event_id), "owner_id": owner_id})
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event

def _validate_event_slug(updates: dict, event_id: Optional[str]):
    slug = updates["custom_slug"].strip().lower()
    if not slug:
        updates["custom_slug"] = None
        return
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,48}[a-z0-9]", slug):
        raise HTTPException(status_code=400,
            detail="Custom link can only contain lowercase letters, numbers, and hyphens (3-50 characters)")
    if slug in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail=f'"{slug}" is reserved and can\'t be used')
    updates["custom_slug"] = slug

@api_router.get("/events")
async def list_events(user: dict = Depends(get_current_user)):
    cur = db.events.find({"owner_id": user["_id"]}).sort("start_date", -1)
    return [ser_event(d) async for d in cur]

@api_router.post("/events")
async def create_event(body: EventCreate, user: dict = Depends(get_current_user)):
    if body.currency not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    doc = body.model_dump()
    doc["owner_id"] = user["_id"]
    doc["status"] = "draft"
    doc["share_token"] = secrets.token_urlsafe(24)
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.events.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_event(doc)

@api_router.get("/events/{event_id}")
async def get_event(event_id: str, user: dict = Depends(get_current_user)):
    return ser_event(await _get_owned_event(event_id, user["_id"]))

@api_router.patch("/events/{event_id}")
async def update_event(event_id: str, body: EventUpdate, user: dict = Depends(get_current_user)):
    await _get_owned_event(event_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "currency" in updates and updates["currency"] not in SUPPORTED_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {SUPPORTED_CURRENCIES}")
    if "status" in updates and updates["status"] not in EVENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {EVENT_STATUSES}")
    if "custom_slug" in updates:
        _validate_event_slug(updates, event_id)
        if updates["custom_slug"]:
            existing = await db.events.find_one({"custom_slug": updates["custom_slug"], "_id": {"$ne": ObjectId(event_id)}})
            if existing:
                raise HTTPException(status_code=409, detail="That custom link is already taken by another event")
    await db.events.update_one({"_id": ObjectId(event_id)}, {"$set": updates})
    return ser_event(await db.events.find_one({"_id": ObjectId(event_id)}))

@api_router.delete("/events/{event_id}")
async def delete_event(event_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_event(event_id, user["_id"])
    await db.events.delete_one({"_id": ObjectId(event_id)})
    await db.event_registrations.delete_many({"event_id": event_id, "owner_id": user["_id"]})
    return {"ok": True}

@api_router.get("/events/{event_id}/registrations")
async def list_event_registrations(event_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_event(event_id, user["_id"])
    cur = db.event_registrations.find({"event_id": event_id, "owner_id": user["_id"]}).sort("created_at", -1)
    return [ser_event_registration(d) async for d in cur]

@api_router.post("/events/{event_id}/registrations/{reg_id}/approve")
async def approve_event_registration(event_id: str, reg_id: str, body: EventRegistrationApprove,
                                      user: dict = Depends(get_current_user)):
    await _get_owned_event(event_id, user["_id"])
    reg = await db.event_registrations.find_one({"_id": ObjectId(reg_id), "event_id": event_id, "owner_id": user["_id"]})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    updates = {
        "status": "approved",
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    if body.payment_amount is not None:
        updates["payment_amount"] = body.payment_amount
    if body.payment_notes is not None:
        updates["payment_notes"] = body.payment_notes
    await db.event_registrations.update_one({"_id": reg["_id"]}, {"$set": updates})
    return ser_event_registration(await db.event_registrations.find_one({"_id": reg["_id"]}))

@api_router.post("/events/{event_id}/push-invite")
async def push_event_invite(event_id: str, body: EventPushInviteRequest, user: dict = Depends(get_current_user)):
    event = await _get_owned_event(event_id, user["_id"])
    q = {"event_id": event_id, "owner_id": user["_id"], "status": "approved"}
    if body.registration_ids:
        q["_id"] = {"$in": [ObjectId(rid) for rid in body.registration_ids]}
    owner = await db.users.find_one({"_id": ObjectId(user["_id"])})
    teacher_name = owner.get("teacher_name") or owner.get("name") if owner else None
    sent, failed = [], []
    async for reg in db.event_registrations.find(q):
        try:
            await email_service.send_event_invite_email(
                reg["email"], reg.get("name"), event.get("name"), teacher_name,
                event.get("zoom_meeting_id"), event.get("zoom_passcode"),
                event.get("start_date"), event.get("time"),
            )
            await db.event_registrations.update_one(
                {"_id": reg["_id"]},
                {"$set": {"status": "invited", "invited_at": datetime.now(timezone.utc).isoformat()}}
            )
            sent.append(str(reg["_id"]))
        except Exception as e:
            logger.error(f"Event invite email failed for {reg.get('email')}: {e}")
            failed.append(str(reg["_id"]))
    return {"sent": sent, "failed": failed}

@api_router.get("/events/{event_id}/registrations/{reg_id}/proof")
async def get_event_registration_proof(event_id: str, reg_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_event(event_id, user["_id"])
    reg = await db.event_registrations.find_one({"_id": ObjectId(reg_id), "event_id": event_id, "owner_id": user["_id"]})
    if not reg or not reg.get("payment_proof_path"):
        raise HTTPException(status_code=404, detail="No proof on file")
    try:
        data, ct = get_object(reg["payment_proof_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="File unavailable")
    return Response(content=data, media_type=ct or "application/octet-stream")

def _age_from_dob(dob: Optional[str]) -> Optional[int]:
    if not dob:
        return None
    try:
        born = datetime.strptime(dob[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = datetime.now(timezone.utc).date()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

# --------------- Announcements -----------------
async def _get_owned_announcement(announcement_id: str, owner_id: str) -> dict:
    a = await db.announcements.find_one({"_id": ObjectId(announcement_id), "owner_id": owner_id})
    if not a:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return a

@api_router.get("/announcements")
async def list_announcements(user: dict = Depends(get_current_user)):
    """Newest first, with a read/unread count against currently active
    students — retracted posts stay listed (struck through client-side) so
    there's a record of what was said and un-said, rather than vanishing."""
    active_count = await db.students.count_documents({"owner_id": user["_id"], "is_active": {"$ne": False}})
    out = []
    cur = db.announcements.find({"owner_id": user["_id"]}).sort("created_at", -1)
    async for a in cur:
        item = ser_announcement(a)
        read_count = await db.announcement_reads.count_documents({"announcement_id": str(a["_id"])})
        item["read_count"] = read_count
        item["total_students"] = active_count
        out.append(item)
    return out

@api_router.post("/announcements")
async def create_announcement(body: AnnouncementCreate, user: dict = Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    doc = body.model_dump()
    doc["owner_id"] = user["_id"]
    doc["is_retracted"] = False
    doc["created_at"] = now
    doc["updated_at"] = now
    res = await db.announcements.insert_one(doc)
    doc["_id"] = res.inserted_id

    owner = await db.users.find_one({"_id": ObjectId(user["_id"])})
    teacher_name = (owner or {}).get("teacher_name") or (owner or {}).get("name") or "Your teacher"
    preview = body.body if len(body.body) <= 120 else body.body[:117] + "..."
    async for s in db.students.find({"owner_id": user["_id"], "is_active": {"$ne": False}}):
        await push_service.send_push(
            "student", str(s["_id"]), f"New update from {teacher_name}", preview, "/portal/announcements",
        )
    return ser_announcement(doc)

@api_router.patch("/announcements/{announcement_id}")
async def update_announcement(announcement_id: str, body: AnnouncementUpdate, user: dict = Depends(get_current_user)):
    await _get_owned_announcement(announcement_id, user["_id"])
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.announcements.update_one({"_id": ObjectId(announcement_id)}, {"$set": updates})
    return ser_announcement(await db.announcements.find_one({"_id": ObjectId(announcement_id)}))

@api_router.post("/announcements/{announcement_id}/retract")
async def retract_announcement(announcement_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_announcement(announcement_id, user["_id"])
    await db.announcements.update_one(
        {"_id": ObjectId(announcement_id)},
        {"$set": {"is_retracted": True, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return ser_announcement(await db.announcements.find_one({"_id": ObjectId(announcement_id)}))

@api_router.post("/announcements/{announcement_id}/unretract")
async def unretract_announcement(announcement_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_announcement(announcement_id, user["_id"])
    await db.announcements.update_one(
        {"_id": ObjectId(announcement_id)},
        {"$set": {"is_retracted": False, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return ser_announcement(await db.announcements.find_one({"_id": ObjectId(announcement_id)}))

@api_router.delete("/announcements/{announcement_id}")
async def delete_announcement(announcement_id: str, user: dict = Depends(get_current_user)):
    await _get_owned_announcement(announcement_id, user["_id"])
    await db.announcements.delete_one({"_id": ObjectId(announcement_id)})
    await db.announcement_reads.delete_many({"announcement_id": announcement_id})
    return {"ok": True}

@api_router.get("/student/announcements")
async def list_student_announcements(student: dict = Depends(get_current_student)):
    out = []
    cur = db.announcements.find({"owner_id": student["owner_id"], "is_retracted": {"$ne": True}}).sort("created_at", -1)
    async for a in cur:
        item = ser_announcement(a)
        read = await db.announcement_reads.find_one({"announcement_id": str(a["_id"]), "student_id": student["_id"]})
        item["read"] = bool(read)
        out.append(item)
    return out

@api_router.post("/student/announcements/{announcement_id}/read")
async def mark_announcement_read(announcement_id: str, student: dict = Depends(get_current_student)):
    a = await db.announcements.find_one({"_id": ObjectId(announcement_id), "owner_id": student["owner_id"]})
    if not a:
        raise HTTPException(status_code=404, detail="Announcement not found")
    await db.announcement_reads.update_one(
        {"announcement_id": announcement_id, "student_id": student["_id"]},
        {"$setOnInsert": {"read_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    return {"ok": True}

@api_router.get("/crm/contacts")
async def list_crm_contacts(
    q: Optional[str] = None,
    country: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
    event_id: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """Contact list enriched with derived, cross-registration fields —
    events_participated, latest freetext experience, and age — since none of
    those live on the crm_contacts record itself (a contact can register for
    several events, each with its own experience text and status)."""
    contacts = [d async for d in db.crm_contacts.find({"owner_id": user["_id"]})]
    contact_ids = [str(c["_id"]) for c in contacts]

    regs_by_contact: dict = {}
    async for r in db.event_registrations.find({"owner_id": user["_id"], "crm_contact_id": {"$in": contact_ids}}):
        regs_by_contact.setdefault(r["crm_contact_id"], []).append(r)

    event_names = {}
    if regs_by_contact:
        all_event_ids = {r["event_id"] for regs in regs_by_contact.values() for r in regs}
        async for ev in db.events.find({"_id": {"$in": [ObjectId(eid) for eid in all_event_ids]}}):
            event_names[str(ev["_id"])] = ev.get("name")

    opens_by_contact: dict = {}
    async for o in db.crm_invite_opens.find({"owner_id": user["_id"], "contact_id": {"$in": contact_ids}}):
        existing = opens_by_contact.get(o["contact_id"])
        if not existing or (o.get("sent_at") or "") > (existing.get("sent_at") or ""):
            opens_by_contact[o["contact_id"]] = o

    out = []
    for c in contacts:
        cid = str(c["_id"])
        regs = regs_by_contact.get(cid, [])
        regs.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        item = ser_crm_contact(c)
        item["age"] = _age_from_dob(c.get("dob"))
        item["events_participated"] = [
            {"event_id": r["event_id"], "event_name": event_names.get(r["event_id"]), "status": r.get("status")}
            for r in regs
        ]
        item["latest_experience"] = next((r.get("experience") for r in regs if r.get("experience")), None)
        latest_open = opens_by_contact.get(cid)
        item["latest_invite"] = {
            "sent_at": latest_open.get("sent_at"),
            "opened_at": latest_open.get("opened_at"),
            "clicked_at": latest_open.get("clicked_at"),
        } if latest_open else None

        if country and (c.get("country") or "").strip().lower() != country.strip().lower():
            continue
        if min_age is not None and (item["age"] is None or item["age"] < min_age):
            continue
        if max_age is not None and (item["age"] is None or item["age"] > max_age):
            continue
        if event_id and not any(r["event_id"] == event_id for r in regs):
            continue
        if q:
            needle = q.strip().lower()
            haystack = " ".join(filter(None, [
                c.get("name"), c.get("email"), item["latest_experience"],
            ])).lower()
            if needle not in haystack:
                continue

        out.append(item)

    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out

@api_router.get("/crm/contacts/already-invited")
async def crm_already_invited(event_id: str, user: dict = Depends(get_current_user)):
    """Which of this owner's contacts have already been sent an invite for
    this event — lets the frontend warn/pre-filter before a bulk-invite
    accidentally re-spams someone."""
    cids = set()
    async for o in db.crm_invite_opens.find({"owner_id": user["_id"], "event_id": event_id}):
        cids.add(o["contact_id"])
    return {"contact_ids": list(cids)}

@api_router.post("/crm/contacts/bulk-invite")
async def crm_bulk_invite(body: CrmBulkInviteRequest, user: dict = Depends(get_current_user)):
    event = await _get_owned_event(body.event_id, user["_id"])
    if event.get("status") != "published":
        raise HTTPException(status_code=400, detail="Publish the event before inviting contacts")
    link = f"https://{PUBLIC_ROOT_DOMAIN}/{event['custom_slug']}" if event.get("custom_slug") \
        else f"{os.environ.get('APP_URL', '').rstrip('/')}/event/{event['share_token']}"
    owner = await db.users.find_one({"_id": ObjectId(user["_id"])})
    teacher_name = (owner or {}).get("teacher_name") or (owner or {}).get("name") if owner else None
    backend_url = os.environ.get("BACKEND_URL", "").rstrip("/")

    already_invited = set()
    if not body.force:
        async for o in db.crm_invite_opens.find({"owner_id": user["_id"], "event_id": body.event_id}):
            already_invited.add(o["contact_id"])

    campaign_id = str(uuid.uuid4())
    sent, failed, skipped = [], [], []
    for cid in body.contact_ids:
        if cid in already_invited:
            skipped.append(cid)
            continue
        contact = await db.crm_contacts.find_one({"_id": ObjectId(cid), "owner_id": user["_id"]})
        if not contact:
            failed.append(cid)
            continue
        track_token = secrets.token_urlsafe(16)
        try:
            await email_service.send_event_announcement_email(
                contact["email"], contact.get("name"), event.get("name"), teacher_name, link,
                event.get("start_date"), event.get("time"),
                description=event.get("description"), image_event_id=str(event["_id"]) if event.get("image_path") else None,
                track_pixel_url=f"{backend_url}/api/crm/track-open/{track_token}.png",
                track_click_url=f"{backend_url}/api/crm/track-click/{track_token}",
            )
            # Recorded only on a confirmed send — otherwise a failed send would
            # still count toward the duplicate-invite guard and campaign stats,
            # making a contact who never actually got the email look "already
            # invited" and blocking a legitimate retry.
            await db.crm_invite_opens.insert_one({
                "owner_id": user["_id"], "contact_id": cid, "event_id": body.event_id,
                "campaign_id": campaign_id, "track_token": track_token,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "opened_at": None, "clicked_at": None,
            })
            sent.append(cid)
        except Exception as e:
            logger.error(f"Event announcement email failed for {contact.get('email')}: {e}")
            failed.append(cid)
    return {"sent": sent, "failed": failed, "skipped": skipped, "campaign_id": campaign_id if sent else None}

@api_router.get("/crm/campaigns")
async def list_crm_campaigns(user: dict = Depends(get_current_user)):
    """One row per bulk-invite send — sent/opened/clicked counts, for judging
    how a past push performed."""
    campaigns: dict = {}
    async for o in db.crm_invite_opens.find({"owner_id": user["_id"], "campaign_id": {"$exists": True}}):
        cid = o["campaign_id"]
        c = campaigns.setdefault(cid, {
            "campaign_id": cid, "event_id": o["event_id"], "sent_at": o["sent_at"],
            "sent": 0, "opened": 0, "clicked": 0,
        })
        c["sent"] += 1
        if o.get("opened_at"):
            c["opened"] += 1
        if o.get("clicked_at"):
            c["clicked"] += 1
        if o["sent_at"] < c["sent_at"]:
            c["sent_at"] = o["sent_at"]

    event_ids = {c["event_id"] for c in campaigns.values()}
    event_names = {}
    if event_ids:
        async for ev in db.events.find({"_id": {"$in": [ObjectId(eid) for eid in event_ids]}}):
            event_names[str(ev["_id"])] = ev.get("name")

    out = list(campaigns.values())
    for c in out:
        c["event_name"] = event_names.get(c["event_id"])
    out.sort(key=lambda c: c["sent_at"], reverse=True)
    return out

# 1x1 transparent PNG, served as an email open-tracking pixel.
_TRACKING_PIXEL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49444852000000010000000108060000001f15c489"
    "0000000b49444154789c6360000200000500017a5eab3f0000000049454e44ae426082"
)

@api_router.get("/crm/track-open/{track_token}.png")
async def crm_track_open(track_token: str):
    await db.crm_invite_opens.update_one(
        {"track_token": track_token, "opened_at": None},
        {"$set": {"opened_at": datetime.now(timezone.utc).isoformat()}},
    )
    return Response(content=_TRACKING_PIXEL_PNG, media_type="image/png")

@api_router.get("/crm/track-click/{track_token}")
async def crm_track_click(track_token: str):
    send = await db.crm_invite_opens.find_one({"track_token": track_token})
    if send and send.get("clicked_at") is None:
        await db.crm_invite_opens.update_one(
            {"_id": send["_id"]}, {"$set": {"clicked_at": datetime.now(timezone.utc).isoformat()}}
        )
    event = await db.events.find_one({"_id": ObjectId(send["event_id"])}) if send else None
    if not event:
        raise HTTPException(status_code=404, detail="Not found")
    link = f"https://{PUBLIC_ROOT_DOMAIN}/{event['custom_slug']}" if event.get("custom_slug") \
        else f"{os.environ.get('APP_URL', '').rstrip('/')}/event/{event['share_token']}"
    return RedirectResponse(url=link, status_code=302)

# --------------- Outreach templates -----------------
# A small library of raw HTML email templates (cold outreach to schools/
# organizations, not the student-facing announcements/invoices above) that
# Lakshmi can save, fill in per recipient, and send one at a time. The HTML
# is stored and sent exactly as authored — table-based email markup is
# fragile, so this deliberately never parses/rewrites it, only does a
# literal {{Field}} -> value substitution at send time. Sent via the same
# Resend transport as every other app email, but with reply_to set to her
# own address so replies land in her real inbox rather than the app's
# no-reply sender.
@api_router.get("/outreach-templates")
async def list_outreach_templates(user: dict = Depends(get_current_user)):
    cur = db.outreach_templates.find({"owner_id": user["_id"]}).sort("created_at", -1)
    return [ser_outreach_template(d) async for d in cur]

@api_router.post("/outreach-templates")
async def create_outreach_template(body: OutreachTemplateCreate, user: dict = Depends(get_current_user)):
    doc = body.model_dump()
    doc["owner_id"] = user["_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    res = await db.outreach_templates.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_outreach_template(doc)

@api_router.get("/outreach-templates/{template_id}")
async def get_outreach_template(template_id: str, user: dict = Depends(get_current_user)):
    doc = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    return ser_outreach_template(doc)

@api_router.patch("/outreach-templates/{template_id}")
async def update_outreach_template(template_id: str, body: OutreachTemplateUpdate, user: dict = Depends(get_current_user)):
    existing = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.outreach_templates.update_one({"_id": existing["_id"]}, {"$set": updates})
    doc = await db.outreach_templates.find_one({"_id": existing["_id"]})
    return ser_outreach_template(doc)

@api_router.delete("/outreach-templates/{template_id}")
async def delete_outreach_template(template_id: str, user: dict = Depends(get_current_user)):
    res = await db.outreach_templates.delete_one({"_id": ObjectId(template_id), "owner_id": user["_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}

@api_router.post("/outreach-templates/{template_id}/preview")
async def preview_outreach_template(template_id: str, body: OutreachSendRequest, user: dict = Depends(get_current_user)):
    """Same merge as an actual send, without dispatching — powers the live
    preview pane so what she sees is exactly what gets sent."""
    doc = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    html = _merge_outreach_html(doc["html"], body.field_values)
    return {"subject": doc["subject"], "html": html}

async def _do_outreach_send(owner_id: str, doc: dict, body: "OutreachSendRequest",
                             sent_by: str, sent_by_name: Optional[str]) -> dict:
    """Shared by the teacher's own send and a delegated student's send — the
    outreach_sends log is what lets Lakshmi see who actually sent what, so
    every path to sending goes through here rather than duplicating the
    dispatch + logging."""
    html = _merge_outreach_html(doc["html"], body.field_values)

    owner = await db.users.find_one({"_id": ObjectId(owner_id)})
    reply_to = body.reply_to or (owner or {}).get("contact_email") or (owner or {}).get("email")
    payload = {"to": [body.to_email], "subject": doc["subject"], "html": html}
    if reply_to:
        payload["contact_email"] = reply_to
    try:
        result = await email_service.dispatch_email(payload)
    except httpx.HTTPStatusError as e:
        logger.error(f"Outreach send failed: {e.response.status_code} {e.response.text}")
        raise HTTPException(status_code=502, detail="Failed to send email")
    except Exception as e:
        logger.error(f"Outreach send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email")

    await db.outreach_sends.insert_one({
        "owner_id": owner_id,
        "template_id": str(doc["_id"]),
        "template_name": doc.get("name"),
        "to_email": body.to_email,
        "subject": doc["subject"],
        "sent_by": sent_by,  # "teacher" | "student"
        "sent_by_name": sent_by_name,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"ok": True, "to": body.to_email, "email_id": result.get("id")}

@api_router.post("/outreach-templates/{template_id}/send")
async def send_outreach_template(template_id: str, body: OutreachSendRequest, user: dict = Depends(get_current_user)):
    doc = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    teacher_name = user.get("teacher_name") or user.get("name")
    return await _do_outreach_send(user["_id"], doc, body, "teacher", teacher_name)

def ser_outreach_send(doc):
    return {
        "id": str(doc["_id"]),
        "template_id": doc.get("template_id"),
        "template_name": doc.get("template_name"),
        "to_email": doc.get("to_email"),
        "subject": doc.get("subject"),
        "sent_by": doc.get("sent_by"),
        "sent_by_name": doc.get("sent_by_name"),
        "sent_at": doc.get("sent_at"),
    }

@api_router.get("/outreach-sends")
async def list_outreach_sends(user: dict = Depends(get_current_user)):
    """A log of every outreach email actually sent — Lakshmi's own sends and
    any sent on her behalf by a student with Outreach access, newest
    first."""
    cur = db.outreach_sends.find({"owner_id": user["_id"]}).sort("sent_at", -1).limit(200)
    return [ser_outreach_send(d) async for d in cur]

# --------------- Outreach templates: student-delegated access -----------------
# Mirrors the teacher endpoints above for a student Lakshmi has explicitly
# granted access to (see /students/{sid}/outreach-access) — same
# functionality (list/create/edit/preview/send templates owned by the
# teacher), except a student can never delete a template, to guard against
# an accidental deletion of Lakshmi's own library.
async def get_current_student_with_outreach_access(request: Request) -> dict:
    student = await get_current_student(request)
    if not student.get("outreach_access"):
        raise HTTPException(status_code=403, detail="Outreach access has not been enabled for this account")
    return student

@api_router.get("/student/outreach-templates")
async def list_outreach_templates_student(student: dict = Depends(get_current_student_with_outreach_access)):
    cur = db.outreach_templates.find({"owner_id": student["owner_id"]}).sort("created_at", -1)
    return [ser_outreach_template(d) async for d in cur]

@api_router.post("/student/outreach-templates")
async def create_outreach_template_student(body: OutreachTemplateCreate, student: dict = Depends(get_current_student_with_outreach_access)):
    doc = body.model_dump()
    doc["owner_id"] = student["owner_id"]
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    res = await db.outreach_templates.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_outreach_template(doc)

@api_router.get("/student/outreach-templates/{template_id}")
async def get_outreach_template_student(template_id: str, student: dict = Depends(get_current_student_with_outreach_access)):
    doc = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": student["owner_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    return ser_outreach_template(doc)

@api_router.patch("/student/outreach-templates/{template_id}")
async def update_outreach_template_student(template_id: str, body: OutreachTemplateUpdate, student: dict = Depends(get_current_student_with_outreach_access)):
    existing = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": student["owner_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Template not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.outreach_templates.update_one({"_id": existing["_id"]}, {"$set": updates})
    doc = await db.outreach_templates.find_one({"_id": existing["_id"]})
    return ser_outreach_template(doc)

@api_router.post("/student/outreach-templates/{template_id}/preview")
async def preview_outreach_template_student(template_id: str, body: OutreachSendRequest, student: dict = Depends(get_current_student_with_outreach_access)):
    doc = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": student["owner_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    html = _merge_outreach_html(doc["html"], body.field_values)
    return {"subject": doc["subject"], "html": html}

@api_router.post("/student/outreach-templates/{template_id}/send")
async def send_outreach_template_student(template_id: str, body: OutreachSendRequest, student: dict = Depends(get_current_student_with_outreach_access)):
    doc = await db.outreach_templates.find_one({"_id": ObjectId(template_id), "owner_id": student["owner_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Template not found")
    return await _do_outreach_send(student["owner_id"], doc, body, "student", student.get("name"))

# --------------- Public event pages & registration -----------------
async def _ser_shared_event(event: dict) -> dict:
    owner = await db.users.find_one({"_id": ObjectId(event["owner_id"])}) if event.get("owner_id") else None
    studio = {
        "studio_name": (owner or {}).get("studio_name"),
        "teacher_name": (owner or {}).get("teacher_name") or (owner or {}).get("name"),
        "social_youtube": (owner or {}).get("social_youtube"),
        "social_instagram": (owner or {}).get("social_instagram"),
        "social_facebook": (owner or {}).get("social_facebook"),
    }
    return {
        "id": str(event["_id"]),
        "name": event.get("name"),
        "start_date": event.get("start_date"),
        "end_date": event.get("end_date"),
        "time": event.get("time"),
        "description": event.get("description"),
        "image_path": event.get("image_path"),
        "social_instagram": event.get("social_instagram"),
        "social_facebook": event.get("social_facebook"),
        "price": event.get("price", 0.0),
        "currency": event.get("currency", "INR"),
        "studio": studio,
    }

async def _get_published_event_or_404(event: Optional[dict]) -> dict:
    if not event or event.get("status") != "published":
        raise HTTPException(status_code=404, detail="Event not found")
    return await _ser_shared_event(event)

@api_router.get("/events/share/{share_token}")
async def get_shared_event(share_token: str):
    event = await db.events.find_one({"share_token": share_token})
    return await _get_published_event_or_404(event)

@api_router.get("/events/slug/{slug}")
async def get_event_by_slug(slug: str):
    event = await db.events.find_one({"custom_slug": slug.lower()})
    return await _get_published_event_or_404(event)

async def _upsert_crm_contact(owner_id: str, body: EventRegistrationCreate) -> str:
    email = body.email.lower().strip()
    existing = await db.crm_contacts.find_one({"owner_id": owner_id, "email": email})
    if existing:
        await db.crm_contacts.update_one(
            {"_id": existing["_id"]},
            {"$set": {
                "name": body.name, "mobile": body.mobile, "city": body.city,
                "country": body.country, "dob": body.dob,
            }}
        )
        return str(existing["_id"])
    doc = {
        "owner_id": owner_id, "name": body.name, "email": email, "mobile": body.mobile,
        "city": body.city, "country": body.country, "dob": body.dob,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.crm_contacts.insert_one(doc)
    return str(res.inserted_id)

async def _get_event_for_public_action(event_id: str) -> dict:
    event = await db.events.find_one({"_id": ObjectId(event_id)})
    if not event or event.get("status") != "published":
        raise HTTPException(status_code=404, detail="Event not found")
    return event

@api_router.post("/events/{event_id}/register")
async def register_for_event(event_id: str, body: EventRegistrationCreate):
    event = await _get_event_for_public_action(event_id)
    crm_contact_id = await _upsert_crm_contact(event["owner_id"], body)
    doc = body.model_dump()
    doc["email"] = doc["email"].lower().strip()
    doc["event_id"] = event_id
    doc["owner_id"] = event["owner_id"]
    doc["status"] = "pending"
    doc["crm_contact_id"] = crm_contact_id
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.event_registrations.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_event_registration(doc)

@api_router.get("/events/{event_id}/registrations/{reg_id}/qr")
async def event_registration_qr(event_id: str, reg_id: str):
    event = await _get_event_for_public_action(event_id)
    reg = await db.event_registrations.find_one({"_id": ObjectId(reg_id), "event_id": event_id})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    owner = await db.users.find_one({"_id": ObjectId(event["owner_id"])})
    upi_vpa = (owner or {}).get("contact_upi")
    price = event.get("price", 0.0)
    if not upi_vpa or price <= 0:
        raise HTTPException(status_code=404, detail="No QR available")
    teacher_name = (owner or {}).get("teacher_name") or (owner or {}).get("name") or ""
    qr_bytes = pdf_service.upi_qr_bytes(upi_vpa, teacher_name, price)
    if not qr_bytes:
        raise HTTPException(status_code=404, detail="QR generation failed")
    return Response(content=qr_bytes, media_type="image/png")

@api_router.get("/events/{event_id}/image")
async def event_public_image(event_id: str):
    event = await _get_event_for_public_action(event_id)
    if not event.get("image_path"):
        raise HTTPException(status_code=404, detail="No image")
    try:
        data, ct = get_object(event["image_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="Image unavailable")
    return Response(content=data, media_type=ct or "image/jpeg")

@api_router.get("/events/{event_id}/bank-details")
async def event_bank_details(event_id: str):
    event = await _get_event_for_public_action(event_id)
    owner = await db.users.find_one({"_id": ObjectId(event["owner_id"])})
    snapshot = invoices_service.build_studio_snapshot(owner)
    return {
        "bank_name": snapshot.get("bank_name"),
        "bank_account_number": snapshot.get("bank_account_number"),
        "bank_ifsc_code": snapshot.get("bank_ifsc_code"),
        "bank_swift_code": snapshot.get("bank_swift_code"),
        "contact_upi": snapshot.get("contact_upi"),
    }

@api_router.post("/events/{event_id}/registrations/{reg_id}/payment")
async def submit_event_registration_payment(event_id: str, reg_id: str, body: EventRegistrationPayment):
    await _get_event_for_public_action(event_id)
    reg = await db.event_registrations.find_one({"_id": ObjectId(reg_id), "event_id": event_id})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    if body.payment_method not in EVENT_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail=f"payment_method must be one of {EVENT_PAYMENT_METHODS}")
    await db.event_registrations.update_one(
        {"_id": reg["_id"]},
        {"$set": {"payment_method": body.payment_method, "payment_reference": body.payment_reference}}
    )
    return ser_event_registration(await db.event_registrations.find_one({"_id": reg["_id"]}))

@api_router.post("/events/{event_id}/registrations/{reg_id}/payment-proof")
async def upload_event_registration_proof(event_id: str, reg_id: str, file: UploadFile = File(...)):
    await _get_event_for_public_action(event_id)
    reg = await db.event_registrations.find_one({"_id": ObjectId(reg_id), "event_id": event_id})
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")
    if not file.content_type or file.content_type not in PAYMENT_PROOF_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Only JPG, PNG, WEBP or PDF files are allowed")
    data = await file.read()
    if len(data) > PAYMENT_PROOF_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File is too large (max 10MB)")
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
    path = f"{APP_NAME}/event-payment-proofs/{reg['owner_id']}/{event_id}/{uuid.uuid4()}.{ext}"
    result = put_object(path, data, file.content_type)
    await db.event_registrations.update_one(
        {"_id": reg["_id"]}, {"$set": {"payment_proof_path": result["path"]}}
    )
    return ser_event_registration(await db.event_registrations.find_one({"_id": reg["_id"]}))

# --------------- Backups -----------------
@api_router.get("/backup/status")
async def backup_status(user: dict = Depends(get_current_user)):
    full = await db.users.find_one({"_id": ObjectId(user["_id"])})
    has_token = bool(full and full.get("google_refresh_token"))
    # A stored refresh token isn't proof it still works — same live-refresh
    # check as /calendar/status, so this card doesn't say "connected" (and
    # offer "Back up now") for a token Google has already killed.
    working = False
    if has_token:
        creds = await calendar_service.get_credentials(user["_id"], scopes=calendar_service.DRIVE_SCOPES)
        working = creds is not None
    return {
        "connected": working,
        "needs_reconnect": has_token and not working,
        "last_backup_at": (full or {}).get("last_backup_at"),
        "last_backup_ok": (full or {}).get("last_backup_ok"),
    }

@api_router.post("/backup/run")
async def backup_run(user: dict = Depends(get_current_user)):
    result = await backup_service.run_daily_backup(user["_id"])
    await db.users.update_one(
        {"_id": ObjectId(user["_id"])},
        {"$set": {
            "last_backup_at": datetime.now(timezone.utc).isoformat(),
            "last_backup_ok": result.get("ok", False),
        }},
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("reason", "Backup failed"))
    return result

@api_router.post("/backup/cron")
async def backup_cron(secret: str = Query(...)):
    """Triggered by a host cron job (no user session available there), so
    auth is a shared secret rather than the normal cookie/bearer flow.
    Runs the backup for the single admin account this app serves."""
    expected = os.environ.get("BACKUP_CRON_SECRET")
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    user = await db.users.find_one({"email": admin_email})
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    result = await backup_service.run_daily_backup(str(user["_id"]))
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "last_backup_at": datetime.now(timezone.utc).isoformat(),
            "last_backup_ok": result.get("ok", False),
        }},
    )
    return result

@api_router.post("/reminders/cron")
async def reminders_cron(secret: str = Query(...)):
    """Triggered every few minutes by a host cron job (no user session
    available there), so auth is a shared secret rather than cookie/bearer.
    Sends 30-min-before class reminder emails to scheduled students for the
    single admin account this app serves."""
    expected = os.environ.get("BACKUP_CRON_SECRET")  # reuse the same shared secret
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    user = await db.users.find_one({"email": admin_email})
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    return await reminders_service.send_due_reminders(str(user["_id"]))

@api_router.post("/transcription/cron")
async def transcription_cron(secret: str = Query(...)):
    """Triggered periodically by a host cron job — transcribes any class
    voice note still marked pending, one request per recording (Whisper has
    no batch endpoint). No-op entirely if OPENAI_API_KEY isn't set."""
    expected = os.environ.get("BACKUP_CRON_SECRET")  # reuse the same shared secret
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not transcription_service.is_configured():
        return {"ok": True, "processed": 0, "reason": "OPENAI_API_KEY not set"}

    processed, failed = 0, 0
    async for c in db.classes.find({"transcript_status": "pending", "audio_path": {"$ne": None}}):
        try:
            data, ct = get_object(c["audio_path"])
            ext = c["audio_path"].rsplit(".", 1)[-1]
            text = await transcription_service.transcribe(data, ct or "audio/webm", f"note.{ext}")
            await db.classes.update_one(
                {"_id": c["_id"]}, {"$set": {"transcript": text, "transcript_status": "done"}}
            )
            processed += 1
        except Exception as e:
            logger.error(f"Transcription failed for class {c['_id']}: {e}")
            await db.classes.update_one({"_id": c["_id"]}, {"$set": {"transcript_status": "failed"}})
            failed += 1
    return {"ok": True, "processed": processed, "failed": failed}

@api_router.post("/calendar/occurrences/cron")
async def occurrences_cron(secret: str = Query(...)):
    """Triggered daily by a host cron job — tops up the rolling occurrence
    horizon (see OCCURRENCE_HORIZON_DAYS) for the single admin account this
    app serves, and prunes expired one-off schedule_blocks the same way
    interactive schedule reads do."""
    expected = os.environ.get("BACKUP_CRON_SECRET")  # reuse the same shared secret
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    user = await db.users.find_one({"email": admin_email})
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    await _prune_expired_one_offs(str(user["_id"]))
    await _top_up_occurrences(str(user["_id"]))
    return {"ok": True}

def _fmt_time_12h_for_email(t: str) -> str:
    h, m = t.split(":")
    h, m = int(h), int(m)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {period}" if m else f"{h12} {period}"

def _class_hours(occ: dict) -> float:
    minutes = _time_to_minutes(occ["end_time"]) - _time_to_minutes(occ["start_time"])
    return round(minutes / 60, 2)

@api_router.post("/unlogged-classes/cron")
async def unlogged_classes_cron(secret: str = Query(...)):
    """Triggered once daily in the evening by a host cron job — finds every
    class_occurrences entry for today that's already ended, has never been
    cancelled, and has no matching classes log entry (same student_id +
    class_date), and emails Lakshmi one summary nudge listing all of them.
    A shared occurrence with several students is checked per-student, since
    each student needs their own logged class row."""
    expected = os.environ.get("BACKUP_CRON_SECRET")  # reuse the same shared secret
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    user = await db.users.find_one({"email": admin_email})
    if not user:
        raise HTTPException(status_code=404, detail="Admin user not found")
    owner_id = str(user["_id"])

    today_str = datetime.now(IST).date().isoformat()
    student_map = {}
    async for s in db.students.find({"owner_id": owner_id}):
        student_map[str(s["_id"])] = s.get("name") or "Student"

    app_url = os.environ.get("APP_URL", "").rstrip("/")
    items = []
    async for occ in db.class_occurrences.find({
        "owner_id": owner_id, "date": today_str, "status": "scheduled",
    }):
        for sid in occ.get("student_ids", []):
            logged = await db.classes.find_one({
                "owner_id": owner_id, "student_id": sid, "class_date": today_str,
            })
            if logged:
                continue
            link = f"{app_url}/classes?student_id={sid}&class_date={today_str}&hours={_class_hours(occ)}" if app_url else ""
            items.append({
                "student_name": student_map.get(sid, "Student"),
                "date_label": "today",
                "start_time": _fmt_time_12h_for_email(occ["start_time"]),
                "link": link,
            })

    if not items:
        return {"ok": True, "sent": False, "unlogged": 0}

    teacher_email = user.get("contact_email") or user.get("email")
    if not teacher_email:
        return {"ok": True, "sent": False, "unlogged": len(items), "reason": "No teacher email on file"}

    classes_link = f"{app_url}/classes" if app_url else ""
    await email_service.send_unlogged_classes_email(teacher_email, items, classes_link)
    return {"ok": True, "sent": True, "unlogged": len(items)}

# --------------- App wiring -----------------
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    # indexes
    await db.users.create_index("email", unique=True)
    await db.students.create_index("owner_id")
    await db.classes.create_index([("owner_id", 1), ("class_date", -1)])
    await db.payments.create_index([("owner_id", 1), ("paid_on", -1)])
    await db.invoices.create_index("invoice_id", unique=True)
    await db.invoices.create_index("share_token", unique=True)
    await db.password_reset_tokens.create_index("token", unique=True)
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.schedule_blocks.create_index([("owner_id", 1), ("day_of_week", 1)])
    await db.schedule_blocks.create_index([("owner_id", 1), ("is_one_off", 1), ("occurs_on", 1)])
    await db.tours.create_index("owner_id")
    await db.tours.create_index("share_token", unique=True)
    await db.tours.create_index("custom_slug", unique=True, sparse=True)
    await db.tour_stops.create_index([("tour_id", 1), ("stop_date", 1)])
    await db.tour_expenses.create_index([("tour_id", 1), ("expense_date", 1)])
    await db.tour_checkins.create_index("tour_id")
    await db.tour_contacts.create_index("tour_id")
    await db.tour_todos.create_index("tour_id")
    await db.tour_invoices.create_index("tour_id")
    await db.tour_invoices.create_index("share_token", unique=True)
    await db.page_visits.create_index([("owner_id", 1), ("dest_key", 1)], unique=True)
    await db.reminders_sent.create_index([("block_id", 1), ("date", 1), ("student_id", 1)], unique=True)
    await db.class_topics.create_index([("owner_id", 1), ("name", 1)], unique=True)
    await db.tour_files.create_index("tour_id")

    # Student portal
    await db.student_invites.create_index("token", unique=True)
    await db.student_invites.create_index("expires_at", expireAfterSeconds=0)
    await db.student_invites.create_index([("student_id", 1), ("used", 1)])
    await db.password_reset_tokens.create_index([("student_id", 1)], sparse=True)
    await db.schedule_change_requests.create_index([("owner_id", 1), ("status", 1)])
    await db.schedule_change_requests.create_index([("student_id", 1), ("created_at", -1)])
    await db.schedule_change_requests.create_index([("student_id", 1), ("block_id", 1), ("status", 1)])
    await db.schedule_skips.create_index([("block_id", 1), ("occurs_on", 1), ("student_id", 1)], unique=True)
    await db.student_notes.create_index([("student_id", 1), ("created_at", -1)])
    await db.payment_proofs.create_index([("owner_id", 1), ("status", 1)])
    await db.payment_proofs.create_index([("student_id", 1), ("uploaded_at", -1)])
    await db.push_subscriptions.create_index("endpoint", unique=True)
    await db.push_subscriptions.create_index([("owner_type", 1), ("owner_id", 1)])

    # Events (workshops)
    await db.events.create_index("owner_id")
    await db.events.create_index("share_token", unique=True)
    await db.events.create_index("custom_slug", unique=True, sparse=True)
    await db.event_registrations.create_index([("event_id", 1), ("created_at", -1)])
    await db.event_registrations.create_index([("owner_id", 1), ("status", 1)])
    await db.crm_contacts.create_index([("owner_id", 1), ("email", 1)], unique=True)
    await db.crm_invite_opens.create_index("track_token", unique=True)
    await db.crm_invite_opens.create_index([("owner_id", 1), ("contact_id", 1)])
    await db.announcements.create_index([("owner_id", 1), ("created_at", -1)])
    await db.announcement_reads.create_index([("announcement_id", 1), ("student_id", 1)], unique=True)
    await db.class_occurrences.create_index([("owner_id", 1), ("date", 1)])
    await db.class_occurrences.create_index([("block_id", 1), ("date", 1)])
    await db.class_occurrences.create_index([("owner_id", 1), ("student_ids", 1), ("date", 1)])
    await db.personal_events.create_index([("owner_id", 1), ("date", 1)])
    await db.outreach_templates.create_index([("owner_id", 1), ("created_at", -1)])
    await db.outreach_sends.create_index([("owner_id", 1), ("sent_at", -1)])

    # Seed / migrate admin (single-user app)
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    admin_name = os.environ.get("ADMIN_NAME", "Admin")

    existing_by_email = await db.users.find_one({"email": admin_email})
    other_admin = await db.users.find_one({"role": "admin", "email": {"$ne": admin_email}})

    if existing_by_email is None and other_admin is not None:
        # Rename the existing admin to the new email (single-user migration)
        await db.users.update_one(
            {"_id": other_admin["_id"]},
            {"$set": {
                "email": admin_email,
                "password_hash": hash_password(admin_password),
                "name": admin_name,
            }},
        )
        logger.info(f"Migrated admin account to {admin_email}")
    elif existing_by_email is None:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": admin_name,
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded admin user {admin_email}")
    else:
        updates = {}
        if not verify_password(admin_password, existing_by_email["password_hash"]):
            updates["password_hash"] = hash_password(admin_password)
        if existing_by_email.get("name") != admin_name:
            updates["name"] = admin_name
        if updates:
            await db.users.update_one({"_id": existing_by_email["_id"]}, {"$set": updates})
            logger.info(f"Updated admin fields: {list(updates.keys())}")

    # Init storage
    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
