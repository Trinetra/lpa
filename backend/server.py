from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

import os
import io
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import bcrypt
import httpx
import jwt
import requests
import secrets
from collections import defaultdict
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Depends, Query, Header
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

# --------------- Config -----------------
JWT_ALGORITHM = "HS256"
APP_NAME = os.environ.get("APP_NAME", "dance-billing")
# Email-configured flag: true when a Resend key is set. services/email.py
# picks the right transport at call time.
EMAIL_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Lakshmi Studio Ledger")


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
    social_youtube: Optional[str] = None
    social_instagram: Optional[str] = None
    social_facebook: Optional[str] = None
    international_payment_details: Optional[str] = None

class StudentCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    level: Optional[str] = None
    joined_on: Optional[str] = None  # ISO date str
    description: Optional[str] = None
    hourly_rate: float = 0.0
    photo_path: Optional[str] = None

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    level: Optional[str] = None
    joined_on: Optional[str] = None
    description: Optional[str] = None
    hourly_rate: Optional[float] = None
    photo_path: Optional[str] = None

class ClassLogCreate(BaseModel):
    student_id: str
    hours: float
    class_date: str  # ISO
    notes: Optional[str] = None
    rate_override: Optional[float] = None

class ClassLogUpdate(BaseModel):
    hours: Optional[float] = None
    class_date: Optional[str] = None
    notes: Optional[str] = None
    rate_override: Optional[float] = None
    student_id: Optional[str] = None

class PaymentCreate(BaseModel):
    student_id: str
    amount: float
    paid_on: str  # ISO
    method: Optional[str] = None
    notes: Optional[str] = None

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

class ScheduleBlockUpdate(BaseModel):
    day_of_week: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    student_ids: Optional[List[str]] = None
    notes: Optional[str] = None

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

class TourTodoCreate(BaseModel):
    text: str

class TourTodoUpdate(BaseModel):
    text: Optional[str] = None
    done: Optional[bool] = None

TOUR_CURRENCIES = ["INR", "EUR", "USD", "GBP"]
CURRENCY_SYMBOLS = {"INR": "₹", "EUR": "€", "USD": "$", "GBP": "£"}

class TourInvoiceCreate(BaseModel):
    contact_id: Optional[str] = None
    recipient_name: str
    recipient_email: Optional[EmailStr] = None
    description: str
    invoice_date: str  # ISO date
    amount: float
    currency: str = "INR"

class TourInvoiceUpdate(BaseModel):
    recipient_name: Optional[str] = None
    recipient_email: Optional[str] = None
    description: Optional[str] = None
    invoice_date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    paid: Optional[bool] = None

class TourInvoiceSend(BaseModel):
    channels: List[str] = Field(default_factory=lambda: ["email"])  # 'email' and/or 'whatsapp'

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
        "photo_path": doc.get("photo_path"),
        "created_at": doc.get("created_at"),
    }

def ser_class(doc):
    return {
        "id": str(doc["_id"]),
        "student_id": doc.get("student_id"),
        "hours": doc.get("hours"),
        "class_date": doc.get("class_date"),
        "notes": doc.get("notes"),
        "rate": doc.get("rate"),
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

def ser_tour_todo(doc):
    return {
        "id": str(doc["_id"]),
        "tour_id": doc.get("tour_id"),
        "text": doc.get("text"),
        "done": doc.get("done", False),
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
    email = body.email.lower().strip()
    user = await db.users.find_one({"email": email})
    # Always return success (don't leak whether email exists)
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": str(user["_id"]),
            "email": email,
            "used": False,
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        })
        app_url = os.environ.get("APP_URL", "").rstrip("/")
        reset_link = f"{app_url}/reset-password?token={token}"
        logger.info(f"Password reset link for {email}: {reset_link}")
        await _send_password_reset_email(email, user.get("name") or "", reset_link)
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
    await db.users.update_one(
        {"_id": ObjectId(rec["user_id"])},
        {"$set": {"password_hash": hash_password(body.new_password)}}
    )
    await db.password_reset_tokens.update_one(
        {"_id": rec["_id"]}, {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}}
    )
    return {"ok": True}

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
        "social_youtube": user_doc.get("social_youtube"),
        "social_instagram": user_doc.get("social_instagram"),
        "social_facebook": user_doc.get("social_facebook"),
        "international_payment_details": user_doc.get("international_payment_details"),
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

@api_router.post("/classes")
async def create_class(body: ClassLogCreate, user: dict = Depends(get_current_user)):
    student = await db.students.find_one(
        {"_id": ObjectId(body.student_id), "owner_id": user["_id"]}
    )
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    rate = body.rate_override if body.rate_override is not None else student.get("hourly_rate", 0.0)
    doc = {
        "owner_id": user["_id"],
        "student_id": body.student_id,
        "hours": body.hours,
        "class_date": body.class_date,
        "notes": body.notes,
        "rate": rate,
        "amount": round(body.hours * rate, 2),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.classes.insert_one(doc)
    doc["_id"] = res.inserted_id
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

    await db.classes.update_one({"_id": ObjectId(cid)}, {"$set": updates})
    doc = await db.classes.find_one({"_id": ObjectId(cid)})
    return ser_class(doc)

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
    return await compute_student_summary(user["_id"], sid)

@api_router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    total_billed = 0.0
    total_paid = 0.0
    student_map = {}
    async for s in db.students.find({"owner_id": user["_id"]}):
        student_map[str(s["_id"])] = s
    per_student = []
    for sid, s in student_map.items():
        summ = await compute_student_summary(user["_id"], sid)
        total_billed += summ["total_billed"]
        total_paid += summ["total_paid"]
        per_student.append({
            "student_id": sid,
            "name": s.get("name"),
            "photo_path": s.get("photo_path"),
            "level": s.get("level"),
            **summ,
        })
    per_student.sort(key=lambda x: x["balance_due"], reverse=True)
    # recent classes
    recent = []
    cur = db.classes.find({"owner_id": user["_id"]}).sort("class_date", -1).limit(10)
    async for c in cur:
        item = ser_class(c)
        st = student_map.get(c["student_id"])
        item["student_name"] = st.get("name") if st else "Unknown"
        recent.append(item)
    return {
        "total_students": len(student_map),
        "total_billed": round(total_billed, 2),
        "total_paid": round(total_paid, 2),
        "total_due": round(total_billed - total_paid, 2),
        "students": per_student,
        "recent_classes": recent,
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

@api_router.get("/schedule")
async def list_schedule(user: dict = Depends(get_current_user)):
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
    res = await db.tour_stops.insert_one(doc)
    doc["_id"] = res.inserted_id
    return ser_tour_stop(doc)

@api_router.patch("/tours/{tour_id}/stops/{stop_id}")
async def update_tour_stop(tour_id: str, stop_id: str, body: TourStopUpdate,
                            user: dict = Depends(get_current_user)):
    await _get_owned_tour(tour_id, user["_id"])
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
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
    if body.currency not in TOUR_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {TOUR_CURRENCIES}")
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
    if "currency" in updates and updates["currency"] not in TOUR_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {TOUR_CURRENCIES}")
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
    if body.currency not in TOUR_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {TOUR_CURRENCIES}")
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
    if "currency" in updates and updates["currency"] not in TOUR_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"currency must be one of {TOUR_CURRENCIES}")
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
        contact = None
        if inv.get("contact_id"):
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
@api_router.get("/tours/share/{share_token}")
async def get_shared_tour(share_token: str):
    tour = await db.tours.find_one({"share_token": share_token})
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    cur = db.tour_stops.find({"tour_id": str(tour["_id"])}).sort("stop_date", 1)
    stops = [ser_tour_stop(d) async for d in cur]
    return {
        "name": tour.get("name"),
        "start_date": tour.get("start_date"),
        "end_date": tour.get("end_date"),
        "location": tour.get("location"),
        "stops": stops,
    }

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
    await db.tours.create_index("owner_id")
    await db.tours.create_index("share_token", unique=True)
    await db.tour_stops.create_index([("tour_id", 1), ("stop_date", 1)])
    await db.tour_expenses.create_index([("tour_id", 1), ("expense_date", 1)])
    await db.tour_checkins.create_index("tour_id")
    await db.tour_contacts.create_index("tour_id")
    await db.tour_todos.create_index("tour_id")
    await db.tour_invoices.create_index("tour_id")
    await db.tour_invoices.create_index("share_token", unique=True)

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
