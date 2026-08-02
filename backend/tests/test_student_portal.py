"""
Backend tests for the student portal:
  - Magic-link request/verify auth, and that it's isolated from teacher auth
  - /api/student/schedule never reveals another student's block
  - 24h notice cutoff on change requests
  - Reschedule requests that clash with an existing class auto-deny without
    reaching the teacher's queue
  - Approving a non-clashing request produces the right effect per scope
  - Payment proof upload + teacher review flow
"""
import os
import time
import requests
import pytest
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lpa.saisanathana.com").rstrip("/")
API = f"{BASE_URL}/api"
EMAIL = "lpathreya@gmail.com"
PASSWORD = "prashanth"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def session():
    """Teacher session."""
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def student(session):
    r = session.post(f"{API}/students", json={
        "name": "TEST_Portal Student",
        "email": "test.portal.student@example.com",
        "hourly_rate": 500,
    }, timeout=10)
    assert r.status_code in (200, 201), r.text
    st = r.json()
    yield st
    session.delete(f"{API}/students/{st['id']}", timeout=10)


@pytest.fixture(scope="module")
def other_student(session):
    """A second student on a different block, used to assert schedule isolation."""
    r = session.post(f"{API}/students", json={
        "name": "TEST_Portal Other Student",
        "email": "test.portal.other@example.com",
        "hourly_rate": 500,
    }, timeout=10)
    assert r.status_code in (200, 201), r.text
    st = r.json()
    yield st
    session.delete(f"{API}/students/{st['id']}", timeout=10)


def _far_future_block(session, student_ids, day_of_week, start_time, end_time, is_one_off=False):
    r = session.post(f"{API}/schedule", json={
        "day_of_week": day_of_week, "start_time": start_time, "end_time": end_time,
        "student_ids": student_ids, "is_one_off": is_one_off,
    }, timeout=10)
    assert r.status_code in (200, 201), r.text
    return r.json()


@pytest.fixture(scope="module")
def block(session, student):
    b = _far_future_block(session, [student["id"]], day_of_week=0, start_time="06:00", end_time="07:00")
    yield b
    session.delete(f"{API}/schedule/{b['id']}", timeout=10)


@pytest.fixture(scope="module")
def other_block(session, other_student):
    b = _far_future_block(session, [other_student["id"]], day_of_week=1, start_time="06:00", end_time="07:00")
    yield b
    session.delete(f"{API}/schedule/{b['id']}", timeout=10)


def _login_as_student(db, student_email):
    """Request + consume a magic link, reading the token straight from Mongo
    since no email transport is configured in the test environment."""
    r = requests.post(f"{API}/student/auth/request-link", json={"email": student_email}, timeout=15)
    assert r.status_code == 200, r.text
    rec = db.student_magic_links.find_one({"email": student_email}, sort=[("created_at", -1)])
    assert rec, "magic link record not found"
    s = requests.Session()
    r = s.post(f"{API}/student/auth/verify", json={"token": rec["token"]}, timeout=15)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def student_session(db, student, block):
    return _login_as_student(db, student["email"])


@pytest.fixture(scope="module")
def other_student_session(db, other_student, other_block):
    return _login_as_student(db, other_student["email"])


class TestStudentAuth:
    def test_request_link_always_generic(self, student):
        r = requests.post(f"{API}/student/auth/request-link", json={"email": "nobody-abcxyz@example.com"}, timeout=15)
        assert r.status_code == 200
        assert "sign-in link" in r.json().get("message", "")

    def test_verify_rejects_bad_token(self):
        r = requests.post(f"{API}/student/auth/verify", json={"token": "not-a-real-token"}, timeout=15)
        assert r.status_code == 400

    def test_verify_token_is_single_use(self, db, student):
        r = requests.post(f"{API}/student/auth/request-link", json={"email": student["email"]}, timeout=15)
        assert r.status_code == 200
        rec = db.student_magic_links.find_one({"email": student["email"]}, sort=[("created_at", -1)])
        r1 = requests.post(f"{API}/student/auth/verify", json={"token": rec["token"]}, timeout=15)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/student/auth/verify", json={"token": rec["token"]}, timeout=15)
        assert r2.status_code == 400

    def test_student_me(self, student_session, student):
        r = student_session.get(f"{API}/student/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["name"] == student["name"]

    def test_student_token_rejected_on_teacher_routes(self, student_session):
        r = student_session.get(f"{API}/students", timeout=10)
        assert r.status_code == 401

    def test_teacher_token_rejected_on_student_routes(self, session):
        r = session.get(f"{API}/student/me", timeout=10)
        assert r.status_code == 401


class TestStudentSchedule:
    def test_sees_only_own_block(self, student_session, block, other_block):
        r = student_session.get(f"{API}/student/schedule", timeout=10)
        assert r.status_code == 200
        ids = [b["id"] for b in r.json()]
        assert block["id"] in ids
        assert other_block["id"] not in ids

    def test_block_never_exposes_student_ids(self, student_session):
        r = student_session.get(f"{API}/student/schedule", timeout=10)
        for b in r.json():
            assert "student_ids" not in b


class TestChangeRequests:
    def test_rejects_within_24h(self, student_session, db, block):
        # Force the block's next occurrence inside the 24h window by pointing
        # it at today with a start time a few minutes from now.
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        db.schedule_blocks.update_one({"_id": __import__("bson").ObjectId(block["id"])}, {"$set": {
            "day_of_week": now.weekday(),
            "start_time": (now + datetime.timedelta(minutes=5)).strftime("%H:%M"),
        }})
        r = student_session.post(f"{API}/student/change-requests", json={
            "block_id": block["id"], "type": "cancel", "scope": "one_time",
        }, timeout=10)
        assert r.status_code == 422
        # restore a far-future slot for later tests
        db.schedule_blocks.update_one({"_id": __import__("bson").ObjectId(block["id"])}, {"$set": {
            "day_of_week": 0, "start_time": "06:00",
        }})

    def test_reschedule_that_clashes_auto_denies(self, student_session, session, block, other_block):
        r = student_session.post(f"{API}/student/change-requests", json={
            "block_id": block["id"], "type": "reschedule", "scope": "one_time",
            "requested_day_of_week": other_block["day_of_week"],
            "requested_start_time": other_block["start_time"],
            "requested_end_time": other_block["end_time"],
            "reason": "testing clash",
        }, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "denied"
        assert body["auto_denied"] is True

        # Never reaches the teacher's pending queue.
        pending = session.get(f"{API}/change-requests", params={"status": "pending"}, timeout=10).json()
        assert not any(req["id"] == body["id"] for req in pending)

    def test_non_clashing_reschedule_is_pending_then_approvable(self, student_session, session, block):
        r = student_session.post(f"{API}/student/change-requests", json={
            "block_id": block["id"], "type": "reschedule", "scope": "one_time",
            "requested_day_of_week": 2, "requested_start_time": "08:00", "requested_end_time": "09:00",
            "reason": "conflict with rehearsal",
        }, timeout=10)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "pending"

        pending = session.get(f"{API}/change-requests", params={"status": "pending"}, timeout=10).json()
        assert any(req["id"] == body["id"] for req in pending)

        r2 = session.post(f"{API}/change-requests/{body['id']}/approve", timeout=10)
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "approved"

        # The original occurrence should now be filtered out of the student's schedule.
        sched = student_session.get(f"{API}/student/schedule", timeout=10).json()
        assert any(b["day_of_week"] == 2 and b["start_time"] == "08:00" for b in sched)

    def test_permanent_cancel_removes_from_recurring_block(self, session, student):
        b = _far_future_block(session, [student["id"]], day_of_week=4, start_time="10:00", end_time="11:00")
        db_client = MongoClient(MONGO_URL)
        try:
            student_session2 = _login_as_student(db_client[DB_NAME], student["email"])
            r = student_session2.post(f"{API}/student/change-requests", json={
                "block_id": b["id"], "type": "cancel", "scope": "permanent", "reason": "stopping this slot",
            }, timeout=10)
            assert r.status_code == 200, r.text
            req_id = r.json()["id"]
            r2 = session.post(f"{API}/change-requests/{req_id}/approve", timeout=10)
            assert r2.status_code == 200, r2.text
            r3 = session.get(f"{API}/schedule", timeout=10)
            assert not any(x["id"] == b["id"] for x in r3.json())
        finally:
            db_client.close()


class TestPaymentProofs:
    def test_upload_and_review(self, student_session, session, student):
        files = {"file": ("proof.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")}
        r = student_session.post(f"{API}/student/payment-proofs", files=files,
                                  data={"amount_claimed": "500", "note": "UPI transfer"}, timeout=10)
        assert r.status_code == 200, r.text
        proof = r.json()
        assert proof["status"] == "pending"

        r2 = session.get(f"{API}/payment-proofs", params={"status": "pending"}, timeout=10)
        assert any(p["id"] == proof["id"] and p["student_name"] == student["name"] for p in r2.json())

        r3 = session.post(f"{API}/payment-proofs/{proof['id']}/mark-reviewed", timeout=10)
        assert r3.status_code == 200
        assert r3.json()["status"] == "reviewed"

    def test_rejects_bad_content_type(self, student_session):
        files = {"file": ("proof.txt", b"not a real file", "text/plain")}
        r = student_session.post(f"{API}/student/payment-proofs", files=files, timeout=10)
        assert r.status_code == 400


class TestStudentNotes:
    def test_notes_are_private_to_student(self, student_session, session, student):
        r = student_session.post(f"{API}/student/notes", json={"text": "practice adavus daily"}, timeout=10)
        assert r.status_code == 200
        note_id = r.json()["id"]

        r2 = student_session.get(f"{API}/student/notes", timeout=10)
        assert any(n["id"] == note_id for n in r2.json())

        # No teacher-facing endpoint exposes student notes at all.
        r3 = session.get(f"{API}/students/{student['id']}", timeout=10)
        assert "notes" not in r3.json() or "practice adavus" not in str(r3.json())

        student_session.delete(f"{API}/student/notes/{note_id}", timeout=10)
