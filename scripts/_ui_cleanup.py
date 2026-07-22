import os
import requests
s = requests.Session()
BASE = os.environ.get("BASE_URL", "https://lpa.saisanathana.com") + "/api"
s.post(f"{BASE}/auth/login", json={"email":"lpathreya@gmail.com","password":"prashanth"})
for st in s.get(f"{BASE}/students").json():
    if st["name"].startswith("TEST_"):
        s.delete(f"{BASE}/students/{st['id']}"); print("del student", st["name"])
for inv in s.get(f"{BASE}/invoices").json():
    if (inv.get("student_name") or "").startswith("TEST_"):
        s.delete(f"{BASE}/invoices/{inv['invoice_id']}"); print("del invoice", inv["student_name"])
