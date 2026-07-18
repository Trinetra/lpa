"""
Tests for the bulk-outstanding invoice flow (iteration 6):
  GET  /api/invoices/bulk-preview
  POST /api/invoices/bulk-send

Also verifies the generate_invoice regression path (refactored to use
_create_invoice_for_student internally) and ownership isolation.

Cleans up all TEST_-prefixed students (and their cascaded classes / payments /
invoices) at module teardown.
"""
import os
import re
import uuid
import pytest
import requests
from urllib.parse import unquote, urlparse, parse_qs

# Load REACT_APP_BACKEND_URL from /app/frontend/.env if not present in the env.
if not os.environ.get("REACT_APP_BACKEND_URL"):
    try:
        with open("/app/frontend/.env") as _f:
            for _line in _f:
                if _line.startswith("REACT_APP_BACKEND_URL="):
                    os.environ["REACT_APP_BACKEND_URL"] = _line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "lpathreya@gmail.com"
ADMIN_PASSWORD = "prashanth"

# Resend "delivered@resend.dev" always succeeds
DELIVER_EMAIL = "delivered@resend.dev"


# ---------- session fixtures ----------
@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    yield s
    s.close()


@pytest.fixture(scope="module")
def secondary_session():
    """A second (isolated) user for ownership tests. Registered if not present."""
    s = requests.Session()
    email = "test_bulk_isolated@example.com"
    password = "password123"
    # try register
    reg = s.post(f"{API}/auth/register", json={
        "email": email, "password": password, "name": "TEST_ISO",
    })
    # register might not exist as endpoint -- fall back to login
    if reg.status_code not in (200, 201):
        # Try login
        login = s.post(f"{API}/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            pytest.skip(f"Secondary user unavailable (reg={reg.status_code}, login={login.status_code})")
    yield s
    s.close()


# ---------- helpers ----------
def _create_student(session, name, email=None, phone=None, rate=500.0):
    r = session.post(f"{API}/students", json={
        "name": name,
        "email": email,
        "phone": phone,
        "hourly_rate": rate,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _create_class(session, student_id, hours, class_date):
    r = session.post(f"{API}/classes", json={
        "student_id": student_id,
        "hours": hours,
        "class_date": class_date,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _delete_students_with_prefix(session, prefix="TEST_"):
    r = session.get(f"{API}/students")
    if r.status_code != 200:
        return
    for s in r.json():
        if s.get("name", "").startswith(prefix):
            session.delete(f"{API}/students/{s['id']}")
    # also purge any bulk-generated invoices tied to those students – they are
    # cascaded through student delete? Actually no – invoices are NOT cascaded
    # in server.py. Clean manually by listing invoices and deleting those with
    # TEST_ prefix student names.
    r2 = session.get(f"{API}/invoices")
    if r2.status_code == 200:
        for inv in r2.json():
            if (inv.get("student_name") or "").startswith(prefix):
                session.delete(f"{API}/invoices/{inv['invoice_id']}")


# ---------- global data setup ----------
@pytest.fixture(scope="module", autouse=True)
def seed_students(admin_session):
    """
    Set up 4 test students spanning the reachability matrix:
      TEST_bulk_full     - email+phone, outstanding balance
      TEST_bulk_emailonly- email only, outstanding
      TEST_bulk_phoneonly- phone only, outstanding
      TEST_bulk_none     - no email/phone, outstanding
      TEST_bulk_paid     - email+phone, zero balance (0 classes)
    """
    _delete_students_with_prefix(admin_session)  # start clean

    full = _create_student(admin_session, "TEST_bulk_full",
                           email=DELIVER_EMAIL, phone="+919999900001")
    email_only = _create_student(admin_session, "TEST_bulk_emailonly",
                                 email=DELIVER_EMAIL, phone=None)
    phone_only = _create_student(admin_session, "TEST_bulk_phoneonly",
                                 email=None, phone="+919999900003")
    none = _create_student(admin_session, "TEST_bulk_none",
                           email=None, phone=None)
    paid = _create_student(admin_session, "TEST_bulk_paid",
                           email=DELIVER_EMAIL, phone="+919999900005")

    # give outstanding balances to first 4
    for st in (full, email_only, phone_only, none):
        _create_class(admin_session, st["id"], hours=2.0, class_date="2026-02-10")

    yield {
        "full": full,
        "email_only": email_only,
        "phone_only": phone_only,
        "none": none,
        "paid": paid,
    }
    _delete_students_with_prefix(admin_session)


# =========================================================
# GET /api/invoices/bulk-preview
# =========================================================
class TestBulkPreview:
    def test_requires_auth(self):
        r = requests.get(f"{API}/invoices/bulk-preview")
        assert r.status_code in (401, 403), r.text

    def test_returns_list_with_expected_fields(self, admin_session, seed_students):
        r = admin_session.get(f"{API}/invoices/bulk-preview")
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list) and len(data) >= 5
        for row in data:
            assert set(["student_id", "name", "email", "phone",
                        "balance_due", "window_billed", "window_balance",
                        "channels"]).issubset(row.keys())

    def test_channels_reflect_reachability(self, admin_session, seed_students):
        r = admin_session.get(f"{API}/invoices/bulk-preview").json()
        by_id = {row["student_id"]: row for row in r}
        assert set(by_id[seed_students["full"]["id"]]["channels"]) == {"email", "whatsapp"}
        assert by_id[seed_students["email_only"]["id"]]["channels"] == ["email"]
        assert by_id[seed_students["phone_only"]["id"]]["channels"] == ["whatsapp"]
        assert by_id[seed_students["none"]["id"]]["channels"] == []

    def test_sorted_by_balance_due_desc(self, admin_session):
        r = admin_session.get(f"{API}/invoices/bulk-preview").json()
        balances = [row["balance_due"] for row in r]
        assert balances == sorted(balances, reverse=True)

    def test_window_narrows_billed_and_balance(self, admin_session, seed_students):
        # Full range should include the 2026-02-10 class -> billed=1000
        r_all = admin_session.get(f"{API}/invoices/bulk-preview",
                                  params={"start_date": "2026-02-01",
                                          "end_date": "2026-02-28"}).json()
        by_id_all = {r["student_id"]: r for r in r_all}
        full_id = seed_students["full"]["id"]
        assert by_id_all[full_id]["window_billed"] == 1000.0
        # window balance for a student with no payments in window == billed
        assert by_id_all[full_id]["window_balance"] == 1000.0

        # A narrower window excluding Feb 10 should show 0 billed in window
        r_narrow = admin_session.get(f"{API}/invoices/bulk-preview",
                                     params={"start_date": "2026-03-01",
                                             "end_date": "2026-03-31"}).json()
        by_id_n = {r["student_id"]: r for r in r_narrow}
        assert by_id_n[full_id]["window_billed"] == 0.0
        assert by_id_n[full_id]["window_balance"] == 0.0
        # but overall balance_due unchanged
        assert by_id_n[full_id]["balance_due"] == by_id_all[full_id]["balance_due"]


# =========================================================
# POST /api/invoices/bulk-send
# =========================================================
class TestBulkSend:
    def test_requires_auth(self):
        r = requests.post(f"{API}/invoices/bulk-send", json={
            "public_link_base": BASE_URL,
            "channels": ["email"],
        })
        assert r.status_code in (401, 403)

    def test_empty_channels_400(self, admin_session):
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "public_link_base": BASE_URL,
            "channels": [],
            "student_ids": [],
        })
        assert r.status_code == 400
        assert "channel" in r.text.lower()

    def test_unknown_channel_400(self, admin_session):
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "public_link_base": BASE_URL,
            "channels": ["sms"],
            "student_ids": [],
        })
        assert r.status_code == 400
        assert "unknown" in r.text.lower() or "channel" in r.text.lower()

    def test_send_creates_invoice_and_reports_email_sent(self, admin_session, seed_students):
        full_id = seed_students["full"]["id"]
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "start_date": "2026-02-01",
            "end_date": "2026-02-28",
            "student_ids": [full_id],
            "channels": ["email", "whatsapp"],
            "public_link_base": BASE_URL,
            "message": "TEST_BULK reminder",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["students"] == 1
        assert body["summary"]["emails_sent"] == 1
        assert body["summary"]["whatsapp_links"] == 1
        res = body["results"][0]
        assert res["student_id"] == full_id
        assert res["invoice_id"] and res["share_token"]
        assert res["public_link"].endswith(f"/invoice/{res['share_token']}")
        assert res["public_link"].startswith(BASE_URL)
        assert res["channels"]["email"]["status"] == "sent"
        assert res["channels"]["email"]["to"] == DELIVER_EMAIL
        assert res["channels"]["whatsapp"]["status"] == "ready"

        # WhatsApp url is url-encoded wa.me/{digits}?text=...
        wa_url = res["channels"]["whatsapp"]["url"]
        assert wa_url.startswith("https://wa.me/919999900001?text=")
        parsed = urlparse(wa_url)
        raw_query = parsed.query  # still url-encoded
        # No literal spaces in the raw encoded query
        assert " " not in raw_query
        # Message should be url-encoded (contain %20 for spaces)
        assert "%20" in raw_query
        text = parse_qs(raw_query)["text"][0]  # auto-decoded
        assert "\u20b9" in text  # rupee sign
        assert res["public_link"] in text
        assert "Lakshmi" in text or "TEST_bulk_full" in text

        # verify invoice appears in GET /api/invoices with last_sent_to set
        inv_list = admin_session.get(f"{API}/invoices").json()
        matching = [i for i in inv_list if i["invoice_id"] == res["invoice_id"]]
        assert len(matching) == 1
        assert matching[0]["last_sent_to"] == DELIVER_EMAIL
        assert matching[0]["last_sent_at"]

    def test_skip_semantics_no_email(self, admin_session, seed_students):
        phone_only_id = seed_students["phone_only"]["id"]
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "student_ids": [phone_only_id],
            "channels": ["email", "whatsapp"],
            "public_link_base": BASE_URL,
        })
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["channels"]["email"]["status"] == "skipped"
        assert "no email" in res["channels"]["email"]["reason"].lower()
        assert res["channels"]["whatsapp"]["status"] == "ready"

    def test_skip_semantics_no_phone(self, admin_session, seed_students):
        email_only_id = seed_students["email_only"]["id"]
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "student_ids": [email_only_id],
            "channels": ["email", "whatsapp"],
            "public_link_base": BASE_URL,
        })
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        assert res["channels"]["email"]["status"] == "sent"
        assert res["channels"]["whatsapp"]["status"] == "skipped"
        assert "no phone" in res["channels"]["whatsapp"]["reason"].lower()

    def test_skip_both_channels_when_unreachable(self, admin_session, seed_students):
        none_id = seed_students["none"]["id"]
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "student_ids": [none_id],
            "channels": ["email", "whatsapp"],
            "public_link_base": BASE_URL,
        })
        assert r.status_code == 200, r.text
        res = r.json()["results"][0]
        # invoice should still be created
        assert res["invoice_id"]
        assert res["channels"]["email"]["status"] == "skipped"
        assert res["channels"]["whatsapp"]["status"] == "skipped"

    def test_no_student_ids_only_outstanding(self, admin_session, seed_students):
        """When student_ids is omitted, only students with balance_due>0 are processed."""
        r = admin_session.post(f"{API}/invoices/bulk-send", json={
            "start_date": "2026-02-01", "end_date": "2026-02-28",
            "channels": ["email"],
            "public_link_base": BASE_URL,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        student_ids = {res["student_id"] for res in body["results"]}
        # paid student should NOT be present
        assert seed_students["paid"]["id"] not in student_ids
        # at least one of the outstanding TEST_ students should be present
        outstanding_ids = {seed_students[k]["id"]
                            for k in ("full", "email_only", "phone_only", "none")}
        assert outstanding_ids.intersection(student_ids)


# =========================================================
# Regression: /api/invoices/generate still works after refactor
# =========================================================
class TestGenerateRegression:
    def test_generate_uses_helper_and_returns_expected_fields(self, admin_session,
                                                              seed_students):
        full_id = seed_students["full"]["id"]
        r = admin_session.post(f"{API}/invoices/generate", json={
            "student_id": full_id,
            "start_date": "2026-02-01",
            "end_date": "2026-02-28",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["invoice_id"] and data["share_token"]
        assert set(["summary", "class_count", "payment_count"]).issubset(data.keys())
        assert data["summary"]["total_billed"] == 1000.0
        assert data["class_count"] == 1

        # And the invoice should be readable via shared endpoint (uses helper)
        shared = requests.get(f"{API}/invoices/share/{data['share_token']}")
        assert shared.status_code == 200
        payload = shared.json()
        assert payload["student"]["name"] == "TEST_bulk_full"


# =========================================================
# Ownership isolation
# =========================================================
class TestOwnershipIsolation:
    def test_secondary_user_cannot_see_admin_students(self, secondary_session):
        r = secondary_session.get(f"{API}/invoices/bulk-preview")
        assert r.status_code == 200
        for row in r.json():
            assert not (row.get("name") or "").startswith("TEST_bulk_")

    def test_secondary_user_bulk_send_ignores_admin_ids(self, secondary_session,
                                                        seed_students):
        admin_full_id = seed_students["full"]["id"]
        r = secondary_session.post(f"{API}/invoices/bulk-send", json={
            "student_ids": [admin_full_id],
            "channels": ["email"],
            "public_link_base": BASE_URL,
        })
        assert r.status_code == 200
        assert r.json()["summary"]["students"] == 0
        assert r.json()["results"] == []
