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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from starlette.middleware.cors import CORSMiddleware

from db import client, db
from services import pdf as pdf_service
from services import email as email_service
from services import invoices as invoices_service
from services import storage as storage_service

# --------------- Config -----------------
JWT_ALGORITHM = "HS256"
APP_NAME = os.environ.get("APP_NAME", "dance-billing")
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"  # legacy — services/storage.py owns this now
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
# Email-configured flag: true when either the Emergent proxy key OR a direct
# Resend key is set. services/email.py picks the right transport at call time.
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY") or os.environ.get("RESEND_API_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Lakshmi Studio Ledger")


# Legacy shims — delegate to services.storage. Older call sites in the file
# still reference these names; keeping the shims avoids a wider diff.
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
    # SameSite=None + Secure so cookies work when the app is embedded in the
    # Emergent preview iframe (different parent origin from the backend).
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
                           studio_contact=None):
    return pdf_service.generate_invoice_pdf(
        teacher_name, student, classes, payments, summary, start, end,
        studio_name=studio_name, logo_bytes=logo_bytes, studio_contact=studio_contact,
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


def _origin_from_public_link(public_link):
    return email_service._origin_from_public_link(public_link)


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
