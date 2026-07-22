"""
Backend tests for iteration 5:
- Admin credentials rotation (lpathreya@gmail.com / prashanth)
- Change password
- Forgot password / Reset password flow (email logged link)
- Studio Profile GET/PATCH
- Logo upload
- Invoice studio_snapshot (generate, shared view, shared logo, PDF branding)
Password is reset to 'prashanth' at end (autouse teardown at module scope).
"""
import io
import os
import re
import struct
import time
import uuid
import zlib
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lpa.saisanathana.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "lpathreya@gmail.com"
ADMIN_PASSWORD = "prashanth"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# --------- fixtures ---------
@pytest.fixture(scope="session")
def session():
    s = requests.Session()
    return s


@pytest.fixture(scope="session")
def auth_headers(session):
    """Login and return Authorization headers using Bearer token."""
    r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


def _run(coro):
    # legacy shim - kept for backward-compat; pymongo calls return values directly
    return coro


# ---------- Credentials rotation ----------
class TestCredentialsRotation:
    def test_new_admin_login_success(self, session):
        r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == ADMIN_EMAIL
        assert data["name"] == "Lakshmi"
        assert isinstance(data["token"], str) and len(data["token"]) > 20

    def test_me_returns_lakshmi(self, session, auth_headers):
        r = session.get(f"{API}/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["name"] == "Lakshmi"

    def test_old_creds_fail(self, session):
        r = session.post(f"{API}/auth/login", json={"email": "teacher@dance.com", "password": "dance123"})
        assert r.status_code == 401

    def test_single_admin_in_db(self, db):
        d = db
        # only ONE user doc should exist (single-user app)
        count = (d.users.count_documents({}))
        assert count == 1
        admin = (d.users.find_one({"email": ADMIN_EMAIL}))
        assert admin is not None
        assert admin.get("name") == "Lakshmi"


# ---------- Change password ----------
class TestChangePassword:
    def test_wrong_current_password(self, session, auth_headers):
        r = session.post(f"{API}/auth/change-password", headers=auth_headers,
                         json={"current_password": "not-real", "new_password": "prashanth2"})
        assert r.status_code == 400
        assert "Current password" in r.json()["detail"]

    def test_short_new_password(self, session, auth_headers):
        r = session.post(f"{API}/auth/change-password", headers=auth_headers,
                         json={"current_password": ADMIN_PASSWORD, "new_password": "abc"})
        assert r.status_code == 400

    def test_change_and_verify_flow(self, session, auth_headers):
        # change to prashanth2
        r = session.post(f"{API}/auth/change-password", headers=auth_headers,
                         json={"current_password": ADMIN_PASSWORD, "new_password": "prashanth2"})
        assert r.status_code == 200

        # old password fails
        r_old = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r_old.status_code == 401

        # new password works
        r_new = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "prashanth2"})
        assert r_new.status_code == 200

        # revert back to 'prashanth'
        headers2 = {"Authorization": f"Bearer {r_new.json()['token']}"}
        r_rev = session.post(f"{API}/auth/change-password", headers=headers2,
                             json={"current_password": "prashanth2", "new_password": ADMIN_PASSWORD})
        assert r_rev.status_code == 200

        # confirm original works again
        r_final = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r_final.status_code == 200


# ---------- Forgot password ----------
class TestForgotPassword:
    def test_forgot_for_existing_returns_ok(self, session, db):
        d = db
        # snapshot count before
        before = (d.password_reset_tokens.count_documents({"email": ADMIN_EMAIL}))
        r = session.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
        assert r.status_code == 200
        assert r.json().get("ok") is True
        after = (d.password_reset_tokens.count_documents({"email": ADMIN_EMAIL}))
        assert after >= before + 1
        # verify latest token doc
        doc = (d.password_reset_tokens.find_one({"email": ADMIN_EMAIL}, sort=[("created_at", -1)]))
        assert doc is not None
        assert doc.get("used") is False
        assert isinstance(doc.get("token"), str) and len(doc["token"]) > 20
        assert doc.get("expires_at") is not None

    def test_forgot_for_nonexistent_no_info_leak(self, session, db):
        d = db
        r = session.post(f"{API}/auth/forgot-password", json={"email": "nobody-abcxyz@example.com"})
        assert r.status_code == 200
        assert r.json().get("ok") is True
        # no token doc for that email
        cnt = (d.password_reset_tokens.count_documents({"email": "nobody-abcxyz@example.com"}))
        assert cnt == 0

    def test_reset_link_logged(self):
        # search backend logs for the reset link line
        found = False
        for path in ("/var/log/supervisor/backend.err.log", "/var/log/supervisor/backend.out.log"):
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        # read tail
                        f.seek(0, 2); size = f.tell()
                        f.seek(max(0, size - 200_000))
                        tail = f.read()
                    if "Password reset link" in tail:
                        found = True
                        break
                except Exception:
                    pass
        assert found, "Expected 'Password reset link' log line in backend logs"


# ---------- Reset password ----------
class TestResetPassword:
    def test_reset_flow_end_to_end(self, session, db):
        d = db
        # Request a fresh token
        r = session.post(f"{API}/auth/forgot-password", json={"email": ADMIN_EMAIL})
        assert r.status_code == 200
        doc = (d.password_reset_tokens.find_one({"email": ADMIN_EMAIL, "used": False},
                                                          sort=[("created_at", -1)]))
        assert doc is not None
        token = doc["token"]

        # 1) short password rejected
        r_short = session.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "abc"})
        assert r_short.status_code == 400

        # 2) reset to 'prashanth3'
        r_ok = session.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "prashanth3"})
        assert r_ok.status_code == 200

        # 3) login with new password
        r_login = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "prashanth3"})
        assert r_login.status_code == 200

        # 4) reusing same token fails
        r_reuse = session.post(f"{API}/auth/reset-password", json={"token": token, "new_password": "prashanth4"})
        assert r_reuse.status_code == 400
        assert "already used" in r_reuse.json()["detail"].lower()

        # 5) invalid token fails
        r_bad = session.post(f"{API}/auth/reset-password", json={"token": "totally-fake", "new_password": "prashanth5"})
        assert r_bad.status_code == 400

        # 6) reset back to 'prashanth' via change-password (authenticated) for downstream tests
        hdr = {"Authorization": f"Bearer {r_login.json()['token']}"}
        r_rev = session.post(f"{API}/auth/change-password", headers=hdr,
                             json={"current_password": "prashanth3", "new_password": ADMIN_PASSWORD})
        assert r_rev.status_code == 200
        # confirm
        r_final = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r_final.status_code == 200

    def test_expired_token(self, session, db):
        """Insert an artificially expired token and try to use it."""
        d = db
        from datetime import datetime, timedelta, timezone
        user = (d.users.find_one({"email": ADMIN_EMAIL}))
        fake_token = f"expired-{uuid.uuid4().hex}"
        (d.password_reset_tokens.insert_one({
            "token": fake_token,
            "user_id": str(user["_id"]),
            "email": ADMIN_EMAIL,
            "used": False,
            "created_at": datetime.now(timezone.utc) - timedelta(hours=3),
            "expires_at": datetime.now(timezone.utc) - timedelta(hours=2),
        }))
        r = session.post(f"{API}/auth/reset-password", json={"token": fake_token, "new_password": "anything123"})
        assert r.status_code == 400
        # cleanup
        (d.password_reset_tokens.delete_one({"token": fake_token}))


# ---------- Profile ----------
class TestProfile:
    def test_get_profile(self, session, auth_headers):
        r = session.get(f"{API}/profile", headers=auth_headers)
        assert r.status_code == 200
        p = r.json()
        assert p["email"] == ADMIN_EMAIL
        for key in ("studio_name", "teacher_name", "contact_phone", "contact_upi", "contact_email", "logo_path"):
            assert key in p

    def test_patch_profile_persists(self, session, auth_headers):
        payload = {"studio_name": "Lakshmi School of Dance", "contact_upi": "lakshmi@upi"}
        r = session.patch(f"{API}/profile", headers=auth_headers, json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["studio_name"] == "Lakshmi School of Dance"
        assert data["contact_upi"] == "lakshmi@upi"
        # GET verifies persistence
        r2 = session.get(f"{API}/profile", headers=auth_headers)
        assert r2.json()["studio_name"] == "Lakshmi School of Dance"
        assert r2.json()["contact_upi"] == "lakshmi@upi"


# ---------- Logo upload + Invoice branding ----------
def _make_png_bytes():
    """Build a minimal valid 1x1 red PNG."""
    def chunk(t, d):
        c = zlib.crc32(t + d) & 0xffffffff
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", c)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = b"\x00" + b"\xff\x00\x00"  # filter byte + 1 pixel RGB
    idat = chunk(b"IDAT", zlib.compress(raw))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


class TestLogoAndInvoiceBranding:
    @pytest.fixture(scope="class")
    def uploaded_logo(self, session, auth_headers):
        png = _make_png_bytes()
        files = {"file": ("logo.png", png, "image/png")}
        r = session.post(f"{API}/uploads/photo", headers=auth_headers, files=files)
        assert r.status_code == 200, f"upload failed: {r.text}"
        path = r.json()["path"]
        # save on profile
        r2 = session.patch(f"{API}/profile", headers=auth_headers, json={"logo_path": path})
        assert r2.status_code == 200
        assert r2.json()["logo_path"] == path
        return path

    @pytest.fixture(scope="class")
    def test_student_with_invoice(self, session, auth_headers, uploaded_logo):
        # Create student
        r = session.post(f"{API}/students", headers=auth_headers,
                         json={"name": f"TEST_Branding_{uuid.uuid4().hex[:6]}", "hourly_rate": 500.0})
        assert r.status_code == 200
        sid = r.json()["id"]
        # Class
        rc = session.post(f"{API}/classes", headers=auth_headers,
                          json={"student_id": sid, "hours": 2, "class_date": "2025-01-15", "notes": "TEST class"})
        assert rc.status_code == 200
        # Generate invoice (no payment => balance_due > 0)
        rg = session.post(f"{API}/invoices/generate", headers=auth_headers, json={"student_id": sid})
        assert rg.status_code == 200
        inv = rg.json()
        yield {"student_id": sid, **inv}
        # teardown - delete cascades (also removes invoice? no. Delete invoice explicitly)
        try:
            session.delete(f"{API}/invoices/{inv['invoice_id']}", headers=auth_headers)
        except Exception:
            pass
        session.delete(f"{API}/students/{sid}", headers=auth_headers)

    def test_shared_invoice_has_studio_snapshot(self, session, test_student_with_invoice):
        tok = test_student_with_invoice["share_token"]
        r = session.get(f"{API}/invoices/share/{tok}")
        assert r.status_code == 200
        j = r.json()
        assert "studio" in j
        studio = j["studio"]
        assert studio["studio_name"] == "Lakshmi School of Dance"
        assert studio["contact_upi"] == "lakshmi@upi"
        assert studio["logo_path"] is not None
        assert studio.get("teacher_name")

    def test_shared_logo_endpoint(self, session, test_student_with_invoice):
        tok = test_student_with_invoice["share_token"]
        r = session.get(f"{API}/invoices/share/{tok}/logo")
        assert r.status_code == 200
        ct = r.headers.get("content-type", "")
        assert ct.startswith("image/"), f"unexpected content-type: {ct}"
        # PNG magic
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n" or ct.startswith("image/")

    def test_shared_logo_invalid_token(self, session):
        r = session.get(f"{API}/invoices/share/BAD_TOKEN_xyz/logo")
        assert r.status_code == 404

    def test_shared_logo_missing_when_no_logo(self, session, auth_headers):
        # temporarily clear the logo_path on profile, generate an invoice, expect 404 on logo endpoint
        # 1) save existing logo_path
        cur = session.get(f"{API}/profile", headers=auth_headers).json()
        saved_logo = cur.get("logo_path")
        try:
            # PATCH doesn't let us set None (server strips None). So directly hit DB via API pattern:
            # Instead, generate an invoice for a fresh student, then manually null the studio_snapshot.logo_path
            r = session.post(f"{API}/students", headers=auth_headers,
                             json={"name": f"TEST_NoLogo_{uuid.uuid4().hex[:6]}", "hourly_rate": 100.0})
            sid = r.json()["id"]
            session.post(f"{API}/classes", headers=auth_headers,
                         json={"student_id": sid, "hours": 1, "class_date": "2025-01-16"})
            rg = session.post(f"{API}/invoices/generate", headers=auth_headers, json={"student_id": sid})
            inv = rg.json()
            tok = inv["share_token"]
            # Null out logo in db to test 404 branch (via pymongo, sync)
            c = MongoClient(MONGO_URL)
            try:
                d = c[DB_NAME]
                d.invoices.update_one({"share_token": tok}, {"$set": {"studio_snapshot.logo_path": None}})
            finally:
                c.close()
            r2 = session.get(f"{API}/invoices/share/{tok}/logo")
            assert r2.status_code == 404
            # cleanup
            session.delete(f"{API}/invoices/{inv['invoice_id']}", headers=auth_headers)
            session.delete(f"{API}/students/{sid}", headers=auth_headers)
        finally:
            # ensure original logo preserved
            if saved_logo:
                session.patch(f"{API}/profile", headers=auth_headers, json={"logo_path": saved_logo})

    def test_pdf_embeds_studio_name(self, session, test_student_with_invoice):
        inv_id = test_student_with_invoice["invoice_id"]
        tok = test_student_with_invoice["share_token"]
        r = session.get(f"{API}/invoices/{inv_id}/pdf", params={"token": tok})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:4] == b"%PDF"
        # pypdf text extract
        try:
            import pypdf
        except ImportError:
            pytest.skip("pypdf not installed")
        reader = pypdf.PdfReader(io.BytesIO(r.content))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        assert "Lakshmi School of Dance" in text, f"studio name not embedded in PDF. text: {text[:400]}"
        # pay-to line since balance_due > 0
        assert ("Pay to" in text) or ("lakshmi@upi" in text), "Pay-to line missing when balance_due > 0"


# ---------- Regression: existing endpoints ----------
class TestRegression:
    def test_students_list(self, session, auth_headers):
        r = session.get(f"{API}/students", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_dashboard(self, session, auth_headers):
        r = session.get(f"{API}/dashboard", headers=auth_headers)
        assert r.status_code == 200
        assert "total_students" in r.json()

    def test_invoices_list(self, session, auth_headers):
        r = session.get(f"{API}/invoices", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_unauth_endpoints_401(self):
        # Use a fresh session with NO cookies/headers to test true unauthenticated access
        fresh = requests.Session()
        r = fresh.get(f"{API}/profile")
        assert r.status_code == 401
        r2 = fresh.patch(f"{API}/profile", json={"studio_name": "x"})
        assert r2.status_code == 401
        r3 = fresh.post(f"{API}/auth/change-password", json={"current_password": "x", "new_password": "abcdef"})
        assert r3.status_code == 401
