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
from collections import defaultdict
from bson import ObjectId
from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, UploadFile, File, Depends, Query, Header
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# --------------- Config -----------------
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_ALGORITHM = "HS256"
APP_NAME = os.environ.get("APP_NAME", "dance-billing")
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Kalpana Studio Ledger")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
api_router = APIRouter(prefix="/api")

# --------------- Storage helpers -----------------
storage_key = None

def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key

def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120
    )
    resp.raise_for_status()
    return resp.json()

def get_object(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")

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
    response.set_cookie("access_token", access, httponly=True, secure=False,
                        samesite="lax", max_age=8 * 3600, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=False,
                        samesite="lax", max_age=7 * 24 * 3600, path="/")

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
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
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
        response.set_cookie("access_token", access, httponly=True, secure=False,
                            samesite="lax", max_age=8 * 3600, path="/")
        return {"ok": True}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

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
    # Manual auth: cookie or ?auth=<token>
    token = request.cookies.get("access_token") if request else None
    if not token and auth:
        token = auth
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
def _generate_invoice_pdf(teacher_name: str, student: dict, classes: list,
                          payments: list, summary: dict, start: Optional[str],
                          end: Optional[str]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], fontSize=22,
                                 textColor=colors.HexColor("#D48464"))
    label_style = ParagraphStyle("l", parent=styles["Normal"], fontSize=9,
                                 textColor=colors.HexColor("#666666"))
    body_style = styles["Normal"]

    story = []
    story.append(Paragraph("Invoice", title_style))
    story.append(Paragraph(f"From <b>{teacher_name}</b> — Dance Classes", label_style))
    story.append(Spacer(1, 8 * mm))

    inv_num = f"INV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    period = f"{start or 'All time'} to {end or 'Today'}"
    meta = [
        ["Invoice #", inv_num],
        ["Date", datetime.now(timezone.utc).strftime("%d %b %Y")],
        ["Billed to", student.get("name", "")],
        ["Contact", f"{student.get('email','') or ''} {student.get('phone','') or ''}"],
        ["Period", period],
    ]
    t = Table(meta, colWidths=[35 * mm, 130 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#888888")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph("<b>Classes</b>", body_style))
    story.append(Spacer(1, 3 * mm))
    header = ["Date", "Hours", "Rate (INR/hr)", "Amount (INR)", "Notes"]
    rows = [header]
    for c in classes:
        rows.append([c.get("class_date", ""), f"{c.get('hours', 0)}",
                     f"{c.get('rate', 0)}", f"{c.get('amount', 0)}",
                     c.get("notes") or ""])
    tbl = Table(rows, colWidths=[28 * mm, 18 * mm, 30 * mm, 30 * mm, 60 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5E6D3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1A1816")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
        ("ALIGN", (1, 1), (3, -1), "RIGHT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 6 * mm))

    if payments:
        story.append(Paragraph("<b>Payments Received</b>", body_style))
        story.append(Spacer(1, 3 * mm))
        prows = [["Date", "Method", "Amount (INR)", "Notes"]]
        for p in payments:
            prows.append([p.get("paid_on", ""), p.get("method") or "-",
                          f"{p.get('amount', 0)}", p.get("notes") or ""])
        ptbl = Table(prows, colWidths=[28 * mm, 32 * mm, 30 * mm, 76 * mm], repeatRows=1)
        ptbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5E6D3")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
            ("ALIGN", (2, 1), (2, -1), "RIGHT"),
        ]))
        story.append(ptbl)
        story.append(Spacer(1, 6 * mm))

    # Summary
    total = summary.get("total_billed", 0)
    paid = summary.get("total_paid", 0)
    due = summary.get("balance_due", 0)
    srows = [
        ["Total billed", f"INR {total}"],
        ["Total paid", f"INR {paid}"],
        ["Balance due", f"INR {due}"],
    ]
    stbl = Table(srows, colWidths=[60 * mm, 40 * mm], hAlign="RIGHT")
    stbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#B85C5C")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE", (0, 2), (-1, 2), 0.6, colors.HexColor("#888888")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(stbl)
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "<i>Thank you for learning with us. Please remit any balance at your earliest convenience.</i>",
        label_style))

    doc.build(story)
    buf.seek(0)
    return buf.read()

def _filter_by_date(items: list, start: Optional[str], end: Optional[str], key: str):
    out = []
    for it in items:
        d = it.get(key)
        if start and (not d or d < start):
            continue
        if end and (not d or d > end):
            continue
        out.append(it)
    return out

@api_router.post("/invoices/generate")
async def generate_invoice(body: InvoiceRequest, user: dict = Depends(get_current_user)):
    student = await db.students.find_one({"_id": ObjectId(body.student_id), "owner_id": user["_id"]})
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    classes = []
    async for c in db.classes.find({"owner_id": user["_id"], "student_id": body.student_id}).sort("class_date", 1):
        classes.append(ser_class(c))
    payments = []
    async for p in db.payments.find({"owner_id": user["_id"], "student_id": body.student_id}).sort("paid_on", 1):
        payments.append(ser_payment(p))
    classes = _filter_by_date(classes, body.start_date, body.end_date, "class_date")
    payments = _filter_by_date(payments, body.start_date, body.end_date, "paid_on")

    total_billed = round(sum(float(c["amount"]) for c in classes), 2)
    total_paid = round(sum(float(p["amount"]) for p in payments), 2)
    summary = {
        "total_billed": total_billed,
        "total_paid": total_paid,
        "balance_due": round(total_billed - total_paid, 2),
    }

    invoice_id = str(uuid.uuid4())
    share_token = uuid.uuid4().hex
    invoice_doc = {
        "invoice_id": invoice_id,
        "share_token": share_token,
        "owner_id": user["_id"],
        "student_id": body.student_id,
        "student_snapshot": ser_student(student),
        "teacher_name": user.get("name") or "Dance Teacher",
        "classes": classes,
        "payments": payments,
        "summary": summary,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.invoices.insert_one(invoice_doc)
    return {"invoice_id": invoice_id, "share_token": share_token, "summary": summary,
            "class_count": len(classes), "payment_count": len(payments)}

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
    pdf_bytes = _generate_invoice_pdf(
        inv.get("teacher_name") or "Dance Teacher",
        inv["student_snapshot"], inv["classes"], inv["payments"], inv["summary"],
        inv.get("start_date"), inv.get("end_date"),
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
        "student": inv["student_snapshot"],
        "classes": inv["classes"],
        "payments": inv["payments"],
        "summary": inv["summary"],
        "start_date": inv.get("start_date"),
        "end_date": inv.get("end_date"),
        "created_at": inv.get("created_at"),
    }

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

def _build_invoice_email_html(inv: dict, public_link: str, pdf_link: str,
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

@api_router.post("/invoices/{invoice_id}/send")
async def send_invoice(invoice_id: str, body: SendInvoiceRequest,
                       user: dict = Depends(get_current_user)):
    if not EMAIL_KEY:
        raise HTTPException(status_code=503, detail="Email is not configured")
    inv = await db.invoices.find_one({"invoice_id": invoice_id, "owner_id": user["_id"]})
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_link = body.public_link.split("/invoice/")[0].rstrip("/") if "/invoice/" in body.public_link else ""
    # Better: build pdf link from public link's origin
    origin = body.public_link.split("/invoice/")[0] if "/invoice/" in body.public_link else ""
    api_pdf_link = f"{origin}/api/invoices/{invoice_id}/pdf?token={inv['share_token']}" if origin else ""

    html = _build_invoice_email_html(
        inv, body.public_link, api_pdf_link,
        inv.get("teacher_name") or EMAIL_FROM_NAME, body.message,
    )
    student_name = inv.get("student_snapshot", {}).get("name") or "student"
    subject = f"Invoice from {inv.get('teacher_name') or EMAIL_FROM_NAME}"

    payload = {
        "to": [body.to_email],
        "subject": subject,
        "html": html,
        "from_name": EMAIL_FROM_NAME,
    }
    if body.reply_to:
        payload["contact_email"] = body.reply_to

    try:
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        await db.invoices.update_one(
            {"invoice_id": invoice_id},
            {"$set": {
                "last_sent_to": body.to_email,
                "last_sent_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return {"status": "sent", "to": body.to_email, "student": student_name,
                "email_id": resp.json().get("id")}
    except httpx.HTTPStatusError as e:
        logger.error(f"Email send failed: {e.response.status_code} {e.response.text}")
        raise HTTPException(status_code=502, detail="Failed to send email")
    except Exception as e:
        logger.error(f"Email error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email")

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

    # Seed admin
    admin_email = os.environ.get("ADMIN_EMAIL", "teacher@dance.com").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "dance123")
    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Dance Teacher",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded admin user {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}}
        )
        logger.info(f"Updated admin password for {admin_email}")

    # Init storage
    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
