from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import io
import re
import uuid
import logging
from datetime import datetime, timezone, timedelta, date
from typing import List, Optional
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
CURRENCY_SYMBOLS = {"INR": "₹", "EUR": "€", "USD": "$", "GBP": "£"}

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

class StudentInviteRequest(BaseModel):
    channels: List[str] = Field(default_factory=lambda: ["email"])  # 'email' and/or 'whatsapp'

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
    "portal", "requests", "event", "events", "crm",
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
    force: bool = False  # re-send to contacts already invited to this event

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

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Resolve student for rate calc
    student_id = updates.get("student_id", existing["student_id"])
    student = await db.students.find_one({"_id": ObjectId(student_id), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    hours = updates.get("hours", existing.get("hours"))
    rate_override = updates.get("rate_override")
    # rate_override key present -> use it (may be null explicitly not possible via patch since None is stripped)
    if rate_override is not None:
        rate = rate_override
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

    return {
        "student_currency": student_currency,
        "received_currency": received_currency,
        "received_amount": received_amount,
        "fx_rate": rate,
        "converted_amount": converted_amount,
        "allocations": allocations,
        "unallocated": round(max(remaining, 0), 2),  # overpayment / credit, if any
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

    # Today's scheduled classes, from the recurring weekly schedule (not the
    # classes log, which records classes already given).
    await _prune_expired_one_offs(user["_id"])
    today = date.today()
    today_classes = []
    cur = db.schedule_blocks.find({"owner_id": user["_id"], "day_of_week": today.weekday()}).sort("start_time", 1)
    async for b in cur:
        names = [student_map[sid]["name"] for sid in b.get("student_ids", []) if sid in student_map]
        today_classes.append({
            "id": str(b["_id"]),
            "start_time": b.get("start_time"),
            "end_time": b.get("end_time"),
            "student_names": names,
            "is_one_off": b.get("is_one_off", False),
        })

    # Tour to-dos due today or overdue, still open — across every tour, so
    # she doesn't have to check each tour individually to know what's urgent.
    today_str = today.isoformat()
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
                msg = (f"Hi {s.get('name') or ''}, here's your invoice from {teacher} "
                       f"(₹{doc['summary']['balance_due']} due):\n{entry['public_link']}")
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
    return ser_schedule_block(doc)

@api_router.delete("/schedule/{block_id}")
async def delete_schedule_block(block_id: str, user: dict = Depends(get_current_user)):
    existing = await db.schedule_blocks.find_one({"_id": ObjectId(block_id), "owner_id": user["_id"]})
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule block not found")
    await calendar_service.sync_block_delete(user["_id"], existing.get("google_event_id"))
    await db.schedule_blocks.delete_one({"_id": ObjectId(block_id), "owner_id": user["_id"]})
    return {"ok": True}

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
        "has_password": student.get("_has_password", False),
        "studio_name": (owner or {}).get("studio_name"),
        "teacher_name": (owner or {}).get("teacher_name") or (owner or {}).get("name"),
        "contact_email": (owner or {}).get("contact_email") or (owner or {}).get("email"),
        "contact_phone": (owner or {}).get("contact_phone"),
    }

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

@api_router.get("/student/schedule")
async def student_schedule(student: dict = Depends(get_current_student)):
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
        })
    return out

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
    start_m = _time_to_minutes(start_time)
    end_m = _time_to_minutes(end_time)
    async for b in db.schedule_blocks.find({"owner_id": owner_id, "day_of_week": day_of_week}):
        if exclude_block_id and str(b["_id"]) == exclude_block_id:
            continue
        if _blocks_overlap(start_m, end_m, _time_to_minutes(b["start_time"]), _time_to_minutes(b["end_time"])):
            return True
    return False

@api_router.post("/student/change-requests")
async def create_change_request(body: ChangeRequestCreate, student: dict = Depends(get_current_student)):
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
        clash = await _has_overlap(
            student["owner_id"], body.requested_day_of_week, body.requested_start_time, body.requested_end_time,
            exclude_block_id=body.block_id,
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
    else:
        await calendar_service.sync_block_delete(owner_id, block.get("google_event_id"))
        await db.schedule_blocks.delete_one({"_id": block["_id"]})

async def _retire_one_time_occurrence(owner_id: str, req: dict, block: dict):
    """Called when approving a one_time cancel/reschedule. A recurring block
    just gets this one date skipped (the series itself must survive). But if
    `block` is already a one-off — itself the product of an earlier one_time
    reschedule — there's no series to preserve, so delete it outright instead
    of leaving a stale calendar event behind (a skip would hide it from the
    student's own view, but the teacher's schedule/calendar still shows it,
    forever, since nothing ever prunes a skipped-but-not-expired one-off)."""
    if block.get("is_one_off"):
        await calendar_service.sync_block_delete(owner_id, block.get("google_event_id"))
        await db.schedule_blocks.delete_one({"_id": block["_id"]})
    else:
        await db.schedule_skips.update_one(
            {"block_id": req["block_id"], "occurs_on": req["occurs_on"], "student_id": req["student_id"]},
            {"$set": {"owner_id": owner_id, "source_request_id": str(req["_id"]),
                      "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

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

    if req["type"] == "reschedule":
        clash = await _has_overlap(
            user["_id"], req["requested_day_of_week"], req["requested_start_time"], req["requested_end_time"],
            exclude_block_id=req["block_id"],
        )
        if clash:
            raise HTTPException(
                status_code=409,
                detail="That time now overlaps another class — deny this request or ask the student for a different time",
            )

    if req["type"] == "cancel" and req["scope"] == "one_time":
        await _retire_one_time_occurrence(user["_id"], req, block)
    elif req["type"] == "cancel" and req["scope"] == "permanent":
        await _remove_student_from_block(user["_id"], block, req["student_id"])
    elif req["type"] == "reschedule" and req["scope"] == "one_time":
        await _retire_one_time_occurrence(user["_id"], req, block)
        one_off_doc = {
            "owner_id": user["_id"],
            "day_of_week": req["requested_day_of_week"],
            "start_time": req["requested_start_time"],
            "end_time": req["requested_end_time"],
            "student_ids": [req["student_id"]],
            "notes": f"Rescheduled from {req['occurs_on']} (student request)",
            "is_one_off": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        one_off_doc["occurs_on"] = _next_occurrence(req["requested_day_of_week"])
        res = await db.schedule_blocks.insert_one(one_off_doc)
        one_off_doc["_id"] = res.inserted_id
        names = await _student_names(user["_id"], one_off_doc["student_ids"])
        event_id = await calendar_service.sync_block_upsert(user["_id"], one_off_doc, names)
        if event_id:
            await db.schedule_blocks.update_one({"_id": one_off_doc["_id"]}, {"$set": {"google_event_id": event_id}})
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
    return {
        "configured": calendar_service.is_configured(),
        "connected": bool(full and full.get("google_refresh_token")),
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
    return {
        "connected": bool(full and full.get("google_refresh_token")),
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
