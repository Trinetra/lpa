"""Post-refactor additional checks: PATCH class edits, stats, invoice send, PDF magic bytes."""
import os
import requests

BASE = os.environ.get("BASE_URL", "https://instructor-pay.preview.emergentagent.com").rstrip("/")
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
        results["failed"].append({"name": name, "evidence": str(evidence)[:500]})


s = requests.Session()

# Login
r = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
assert r.status_code == 200, r.text
ok("login", True)

# Create student with rate 500
r = s.post(f"{API}/students", json={"name": "TEST_Refactor Student", "hourly_rate": 500, "joined_on": "2025-01-01"}, timeout=15)
ok("create student", r.status_code in (200, 201), r.text[:200])
student_id = r.json()["id"]

# Create class hours=2 (no override) -> amount=1000
r = s.post(f"{API}/classes", json={"student_id": student_id, "hours": 2, "class_date": "2025-03-01", "notes": "initial"}, timeout=15)
ok("create class hours=2 amount=1000", r.status_code in (200, 201) and r.json().get("amount") in (1000, 1000.0), r.text[:300])
class_id = r.json()["id"]

# PATCH hours=3 with rate_override=600 -> amount=1800
r = s.patch(f"{API}/classes/{class_id}", json={"hours": 3, "rate_override": 600}, timeout=15)
ok("PATCH class hours=3 rate_override=600 -> amount=1800",
   r.status_code == 200 and r.json().get("amount") in (1800, 1800.0),
   f"{r.status_code} {r.text[:400]}")
patched = r.json() if r.status_code == 200 else {}

# PATCH updating notes only (omit rate_override) - amount should remain consistent (either keeps 1800 with 600 override, or re-derives from student rate*3=1500)
r = s.patch(f"{API}/classes/{class_id}", json={"notes": "updated notes only"}, timeout=15)
body = r.json() if r.status_code == 200 else {}
amt = body.get("amount")
# Accept: preserved override -> 1800, OR re-derived to student rate 500 -> 1500. Either is arguably correct.
ok("PATCH class notes only preserves reasonable amount",
   r.status_code == 200 and amt in (1800, 1800.0, 1500, 1500.0),
   f"amount={amt} notes={body.get('notes')} rate_override={body.get('rate_override')} full={body}")
ok("PATCH class notes only updates notes field",
   r.status_code == 200 and body.get("notes") == "updated notes only",
   body)

# Add second class for stats coverage in different month
r_extra = s.post(f"{API}/classes", json={"student_id": student_id, "hours": 1, "class_date": "2025-02-15", "notes": "prior month"}, timeout=15)
ok("create prior-month class", r_extra.status_code in (200, 201), r_extra.text[:200])

# GET /api/stats/monthly?months=3
r = s.get(f"{API}/stats/monthly", params={"months": 3}, timeout=15)
if r.status_code == 200:
    body = r.json()
    months = body.get("months")
    series = body.get("series")
    valid = (isinstance(months, list) and len(months) == 3
             and isinstance(series, list) and len(series) == 3
             and all(("month" in x and "earnings" in x and "hours" in x) for x in series))
    ok("GET /stats/monthly?months=3 shape", valid, body)
else:
    ok("GET /stats/monthly?months=3 shape", False, f"{r.status_code} {r.text[:300]}")

# GET /api/stats/by-student
r = s.get(f"{API}/stats/by-student", timeout=15)
if r.status_code == 200:
    body = r.json()
    is_list = isinstance(body, list)
    keys_ok = all(all(k in x for k in ("student_id", "name", "hours", "amount")) for x in body) if is_list else False
    sorted_ok = True
    if is_list and len(body) >= 2:
        sorted_ok = all(body[i]["amount"] >= body[i+1]["amount"] for i in range(len(body)-1))
    ok("GET /stats/by-student shape & sorted desc", is_list and keys_ok and sorted_ok, body[:3] if is_list else body)
else:
    ok("GET /stats/by-student shape & sorted desc", False, f"{r.status_code} {r.text[:300]}")

# Generate invoice
r = s.post(f"{API}/invoices/generate", json={"student_id": student_id}, timeout=15)
ok("invoice generate", r.status_code in (200, 201), r.text[:300])
inv = r.json()
invoice_id = inv.get("invoice_id")
share_token = inv.get("share_token")

# PDF authenticated - check %PDF magic bytes and size
r = s.get(f"{API}/invoices/{invoice_id}/pdf", timeout=30)
is_pdf = r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 2000
ok("PDF authenticated: %PDF magic + >2KB", is_pdf,
   f"status={r.status_code} ct={r.headers.get('content-type')} len={len(r.content)} head={r.content[:8]!r}")

# PDF public via ?token
r = requests.get(f"{API}/invoices/{invoice_id}/pdf", params={"token": share_token}, timeout=30)
ok("PDF public via ?token: %PDF magic",
   r.status_code == 200 and r.content[:4] == b"%PDF" and "application/pdf" in r.headers.get("content-type",""),
   f"status={r.status_code} ct={r.headers.get('content-type')} len={len(r.content)}")

# POST /invoices/{id}/send with delivered@resend.dev
public_link = f"{BASE}/invoice/{share_token}"
r = s.post(f"{API}/invoices/{invoice_id}/send",
           json={"to_email": "delivered@resend.dev", "public_link": public_link},
           timeout=30)
send_ok = r.status_code == 200
send_body = {}
try:
    send_body = r.json()
except Exception:
    pass
ok("POST /invoices/{id}/send delivered@resend.dev -> 200 status=sent + email_id",
   send_ok and send_body.get("status") == "sent" and bool(send_body.get("email_id")),
   f"status={r.status_code} body={send_body} raw={r.text[:400]}")

# Verify last_sent_to / last_sent_at populated - fetch from /invoices list
r = s.get(f"{API}/invoices", timeout=15)
invs = r.json() if r.status_code == 200 else []
match = None
for iv in invs:
    if iv.get("id") == invoice_id or iv.get("invoice_id") == invoice_id:
        match = iv
        break
ok("invoice last_sent_to/last_sent_at populated after send",
   bool(match) and match.get("last_sent_to") == "delivered@resend.dev" and bool(match.get("last_sent_at")),
   match)

# 404 on non-existent invoice
r = s.post(f"{API}/invoices/000000000000000000000000/send",
           json={"to_email": "delivered@resend.dev", "public_link": public_link},
           timeout=15)
ok("POST /invoices/{fake}/send -> 404", r.status_code == 404, f"{r.status_code} {r.text[:200]}")

# Cleanup
for path in [f"{API}/invoices/{invoice_id}", f"{API}/classes/{class_id}", f"{API}/students/{student_id}"]:
    try:
        s.delete(path, timeout=10)
    except Exception:
        pass

print("\n=== SUMMARY ===")
print(f"Passed: {len(results['passed'])}")
print(f"Failed: {len(results['failed'])}")
for f in results["failed"]:
    print(" -", f)
