"""Backend smoke tests for dance-teacher app."""
import io
import os
import sys
import base64
import requests

BASE = "https://instructor-pay.preview.emergentagent.com"
API = f"{BASE}/api"
EMAIL = "lpathreya@gmail.com"
PASSWORD = "prashanth"

results = {"passed": [], "failed": []}

def ok(name, cond, evidence=""):
    if cond:
        print(f"PASS: {name}")
        results["passed"].append(name)
    else:
        print(f"FAIL: {name} | {evidence}")
        results["failed"].append({"name": name, "evidence": str(evidence)[:400]})

s = requests.Session()

# 1) Login
try:
    r = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    ok("POST /auth/login 200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    user = r.json().get("user") if r.headers.get("content-type", "").startswith("application/json") else None
    ok("login returns user object", bool(user and user.get("email") == EMAIL), r.text[:200])
    token = r.json().get("access_token") if r.headers.get("content-type","").startswith("application/json") else None
except Exception as e:
    ok("login", False, str(e))
    token = None

# 2) /auth/me authenticated
try:
    r = s.get(f"{API}/auth/me", timeout=10)
    ok("GET /auth/me 200 with cookies", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
except Exception as e:
    ok("/auth/me", False, str(e))

# 2b) /auth/me without auth -> 401
try:
    r = requests.get(f"{API}/auth/me", timeout=10)
    ok("/auth/me without auth is 401", r.status_code == 401, f"{r.status_code}")
except Exception as e:
    ok("/auth/me no-auth", False, str(e))

# 3) Create student
student_id = None
try:
    payload = {
        "name": "Test Student",
        "email": "test.student@example.com",
        "phone": "+911234567890",
        "level": "Beginner",
        "joined_on": "2025-01-01",
        "description": "Loves salsa",
        "hourly_rate": 500,
    }
    r = s.post(f"{API}/students", json=payload, timeout=10)
    ok("POST /students 200", r.status_code in (200,201), f"{r.status_code} {r.text[:300]}")
    student = r.json()
    student_id = student.get("id")
    ok("student has id", bool(student_id), student)
except Exception as e:
    ok("create student", False, str(e))

# GET list
try:
    r = s.get(f"{API}/students", timeout=10)
    ok("GET /students lists newly created", r.status_code == 200 and any(x.get("id")==student_id for x in r.json()), f"{r.status_code}")
except Exception as e:
    ok("list students", False, str(e))

# PATCH student
try:
    r = s.patch(f"{API}/students/{student_id}", json={"level": "Intermediate", "hourly_rate": 600}, timeout=10)
    ok("PATCH /students updates fields", r.status_code == 200 and r.json().get("level")=="Intermediate", f"{r.status_code} {r.text[:200]}")
except Exception as e:
    ok("patch student", False, str(e))

# 4) Photo upload - 1x1 PNG
photo_path = None
try:
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    png_bytes = base64.b64decode(png_b64)
    files = {"file": ("pixel.png", io.BytesIO(png_bytes), "image/png")}
    r = s.post(f"{API}/uploads/photo", files=files, timeout=15)
    ok("POST /uploads/photo 200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    photo_path = r.json().get("path")
    ok("upload returns path", bool(photo_path), r.text[:200])
except Exception as e:
    ok("upload photo", False, str(e))

# Fetch file
try:
    r = s.get(f"{API}/uploads/file", params={"path": photo_path}, timeout=15)
    ok("GET /uploads/file serves image", r.status_code==200 and len(r.content) > 0, f"{r.status_code} len={len(r.content)}")
except Exception as e:
    ok("fetch upload", False, str(e))

# Assign photo to student
try:
    r = s.patch(f"{API}/students/{student_id}", json={"photo_path": photo_path}, timeout=10)
    ok("student photo_path saved", r.status_code==200 and r.json().get("photo_path")==photo_path, r.text[:200])
except Exception as e:
    ok("assign photo", False, str(e))

# 5) Log class
class_id = None
try:
    r = s.post(f"{API}/classes", json={"student_id": student_id, "hours": 2, "class_date": "2025-02-01", "notes": "First class", "rate_override": 700}, timeout=10)
    ok("POST /classes 200", r.status_code in (200,201), f"{r.status_code} {r.text[:300]}")
    body = r.json()
    class_id = body.get("id")
    ok("class amount computed = 1400", body.get("amount") in (1400, 1400.0), body)
except Exception as e:
    ok("create class", False, str(e))

# Second class (no override) - uses 600 rate
try:
    r = s.post(f"{API}/classes", json={"student_id": student_id, "hours": 1, "class_date": "2025-02-02", "notes": "Second"}, timeout=10)
    ok("class w/o override uses student rate", r.status_code in (200,201) and r.json().get("amount") in (600, 600.0), f"{r.status_code} {r.text[:200]}")
except Exception as e:
    ok("create class 2", False, str(e))

try:
    r = s.get(f"{API}/classes", params={"student_id": student_id}, timeout=10)
    ok("GET /classes filter by student", r.status_code==200 and len(r.json())>=2, f"{r.status_code}")
except Exception as e:
    ok("list classes", False, str(e))

# 6) Payment
try:
    r = s.post(f"{API}/payments", json={"student_id": student_id, "amount": 1000, "paid_on": "2025-02-05", "method": "UPI", "notes": "partial"}, timeout=10)
    ok("POST /payments 200", r.status_code in (200,201), f"{r.status_code} {r.text[:300]}")
    payment_id = r.json().get("id")
except Exception as e:
    ok("create payment", False, str(e)); payment_id=None

try:
    r = s.get(f"{API}/payments", params={"student_id": student_id}, timeout=10)
    ok("GET /payments filter", r.status_code==200 and len(r.json())>=1, f"{r.status_code}")
except Exception as e:
    ok("list payments", False, str(e))

# 7) Summary
try:
    r = s.get(f"{API}/students/{student_id}/summary", timeout=10)
    body = r.json()
    ok("GET /students/{id}/summary math", r.status_code==200 and body.get("total_billed") in (2000,2000.0) and body.get("total_paid") in (1000,1000.0) and body.get("balance_due") in (1000,1000.0) and body.get("classes_count")==2 and body.get("hours_total") in (3,3.0), body)
except Exception as e:
    ok("summary", False, str(e))

# 8) Dashboard
try:
    r = s.get(f"{API}/dashboard", timeout=10)
    ok("GET /dashboard 200", r.status_code==200, f"{r.status_code} {r.text[:300]}")
    body = r.json()
    ok("dashboard has per-student breakdown", isinstance(body.get("students"), list) and len(body["students"])>=1, list(body.keys()))
    ok("dashboard recent_classes has student_name", any("student_name" in c for c in body.get("recent_classes", [])), body.get("recent_classes", [])[:2])
except Exception as e:
    ok("dashboard", False, str(e))

# 9) Invoice
invoice_id = None; share_token=None
try:
    r = s.post(f"{API}/invoices/generate", json={"student_id": student_id}, timeout=15)
    ok("POST /invoices/generate 200", r.status_code in (200,201), f"{r.status_code} {r.text[:400]}")
    body = r.json()
    invoice_id = body.get("invoice_id"); share_token = body.get("share_token")
    ok("invoice returns id+token", bool(invoice_id and share_token), body)
    ok("invoice summary+counts", body.get("class_count")==2 and body.get("payment_count")==1, body)
except Exception as e:
    ok("gen invoice", False, str(e))

try:
    r = s.get(f"{API}/invoices", timeout=10)
    ok("GET /invoices list", r.status_code==200 and any(x.get("id")==invoice_id or x.get("invoice_id")==invoice_id for x in r.json()), f"{r.status_code}")
except Exception as e:
    ok("list invoices", False, str(e))

# PDF authenticated
try:
    r = s.get(f"{API}/invoices/{invoice_id}/pdf", timeout=20)
    ok("PDF authenticated: application/pdf", r.status_code==200 and "application/pdf" in r.headers.get("content-type","") and len(r.content) > 100, f"{r.status_code} ct={r.headers.get('content-type')} len={len(r.content)}")
except Exception as e:
    ok("pdf auth", False, str(e))

# PDF public via token (no session)
try:
    r = requests.get(f"{API}/invoices/{invoice_id}/pdf", params={"token": share_token}, timeout=20)
    ok("PDF public via ?token", r.status_code==200 and "application/pdf" in r.headers.get("content-type",""), f"{r.status_code} {r.headers.get('content-type')}")
except Exception as e:
    ok("pdf token", False, str(e))

# Share JSON no auth
try:
    r = requests.get(f"{API}/invoices/share/{share_token}", timeout=10)
    ok("GET /invoices/share/{token} no-auth", r.status_code==200, f"{r.status_code} {r.text[:200]}")
except Exception as e:
    ok("share json", False, str(e))

# 10) Ownership isolation - create second user? Skipped (no signup path). Verify unauth cannot list.
try:
    r = requests.get(f"{API}/students", timeout=10)
    ok("unauth GET /students -> 401", r.status_code==401, f"{r.status_code}")
except Exception as e:
    ok("ownership unauth", False, str(e))

# Cleanup deletes
try:
    if payment_id:
        r = s.delete(f"{API}/payments/{payment_id}", timeout=10)
        ok("DELETE /payments", r.status_code in (200,204), f"{r.status_code}")
    if class_id:
        r = s.delete(f"{API}/classes/{class_id}", timeout=10)
        ok("DELETE /classes", r.status_code in (200,204), f"{r.status_code}")
    r = s.delete(f"{API}/students/{student_id}", timeout=10)
    ok("DELETE /students cascades", r.status_code in (200,204), f"{r.status_code}")
    # Confirm cascade removed remaining classes/payments
    r1 = s.get(f"{API}/classes", params={"student_id": student_id}, timeout=10)
    r2 = s.get(f"{API}/payments", params={"student_id": student_id}, timeout=10)
    ok("cascade deleted classes & payments", (r1.status_code==200 and len(r1.json())==0) and (r2.status_code==200 and len(r2.json())==0), f"c={r1.text[:100]} p={r2.text[:100]}")
except Exception as e:
    ok("cleanup", False, str(e))

print("\n=== SUMMARY ===")
print(f"Passed: {len(results['passed'])}")
print(f"Failed: {len(results['failed'])}")
for f in results["failed"]:
    print(" -", f)
