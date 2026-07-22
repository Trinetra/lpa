"""
Regression tests for:
  - New DELETE /api/invoices/{invoice_id} (auth, 404, ownership isolation)
  - DELETE /api/classes and /api/payments (unchanged; smoke)
  - Branding rename: admin display name is 'Lakshmi' (via /auth/me)
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lpa.saisanathana.com").rstrip("/")
API = f"{BASE_URL}/api"
EMAIL = "lpathreya@gmail.com"
PASSWORD = "prashanth"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    token = data.get("token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    s._login = data
    return s


@pytest.fixture(scope="module")
def student(session):
    """Create a throwaway TEST_ student and delete it after the module."""
    r = session.post(f"{API}/students", json={
        "name": "TEST_DeleteInvoice Student",
        "email": "test.delete@example.com",
        "hourly_rate": 500,
    }, timeout=10)
    assert r.status_code in (200, 201), r.text
    st = r.json()
    yield st
    # Cleanup (cascades classes+payments)
    session.delete(f"{API}/students/{st['id']}", timeout=10)


# ---------------- Branding -----------------
class TestBranding:
    def test_login_response_name_is_lakshmi(self, session):
        assert session._login.get("name") == "Lakshmi", session._login

    def test_auth_me_returns_lakshmi(self, session):
        r = session.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body.get("email") == EMAIL
        assert body.get("name") == "Lakshmi", f"Expected 'Lakshmi', got {body.get('name')!r}"


# ---------------- Class + Payment DELETE regression -----------------
class TestClassAndPaymentDelete:
    def test_delete_class_and_verify_gone(self, session, student):
        # create
        r = session.post(f"{API}/classes", json={
            "student_id": student["id"], "hours": 1, "class_date": "2025-03-01",
        }, timeout=10)
        assert r.status_code in (200, 201), r.text
        cid = r.json()["id"]
        # delete
        r = session.delete(f"{API}/classes/{cid}", timeout=10)
        assert r.status_code in (200, 204), r.text
        assert r.json().get("ok") is True
        # verify absent
        r = session.get(f"{API}/classes", params={"student_id": student["id"]}, timeout=10)
        assert not any(c.get("id") == cid for c in r.json())
        # second delete -> 404
        r = session.delete(f"{API}/classes/{cid}", timeout=10)
        assert r.status_code == 404

    def test_delete_payment_and_verify_gone(self, session, student):
        r = session.post(f"{API}/payments", json={
            "student_id": student["id"], "amount": 100, "paid_on": "2025-03-01", "method": "UPI",
        }, timeout=10)
        assert r.status_code in (200, 201), r.text
        pid = r.json()["id"]
        r = session.delete(f"{API}/payments/{pid}", timeout=10)
        assert r.status_code in (200, 204)
        assert r.json().get("ok") is True
        r = session.get(f"{API}/payments", params={"student_id": student["id"]}, timeout=10)
        assert not any(p.get("id") == pid for p in r.json())


# ---------------- Invoice DELETE (new endpoint) -----------------
class TestInvoiceDelete:
    def test_delete_requires_auth(self, session, student):
        # create an invoice
        r = session.post(f"{API}/invoices/generate", json={"student_id": student["id"]}, timeout=15)
        assert r.status_code in (200, 201), r.text
        inv_id = r.json()["invoice_id"]
        share_token = r.json()["share_token"]

        # unauth DELETE -> 401
        r_unauth = requests.delete(f"{API}/invoices/{inv_id}", timeout=10)
        assert r_unauth.status_code == 401, f"expected 401, got {r_unauth.status_code} {r_unauth.text}"

        # still there
        r = session.get(f"{API}/invoices/share/{share_token}", timeout=10)
        assert r.status_code == 200

        # authorized DELETE -> 200 {ok: true}
        r = session.delete(f"{API}/invoices/{inv_id}", timeout=10)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # verify removed from list
        r = session.get(f"{API}/invoices", timeout=10)
        assert not any(i.get("invoice_id") == inv_id for i in r.json())

        # shared-token endpoint now returns 404
        r = requests.get(f"{API}/invoices/share/{share_token}", timeout=10)
        assert r.status_code == 404, r.text

    def test_delete_nonexistent_returns_404(self, session):
        fake = "00000000-0000-0000-0000-000000000000"
        r = session.delete(f"{API}/invoices/{fake}", timeout=10)
        assert r.status_code == 404, r.text

    def test_delete_ownership_isolation(self, session, student):
        """An invoice owned by userA cannot be deleted by someone without owner_id match.
        We can only simulate by attempting with an unauth request (returns 401) and by
        attempting with a random invoice_id from the same account (already 404 covered).
        No signup endpoint exists, so we assert the query filter includes owner_id via
        code path: an invoice we don't own would not match delete_one({owner_id:...}).
        Best we can do here: assert un-owned invoice_id returns 404 (same as not-found),
        which is the expected server behaviour for ownership isolation.
        """
        # generate a new invoice
        r = session.post(f"{API}/invoices/generate", json={"student_id": student["id"]}, timeout=15)
        assert r.status_code in (200, 201)
        inv_id = r.json()["invoice_id"]

        # Corrupt the id (still valid uuid format but different) -> 404
        bogus = inv_id[:-4] + "abcd"
        r = session.delete(f"{API}/invoices/{bogus}", timeout=10)
        assert r.status_code == 404

        # cleanup
        session.delete(f"{API}/invoices/{inv_id}", timeout=10)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
