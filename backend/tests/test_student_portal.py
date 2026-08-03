"""
Backend tests for the student portal:
  - Invite-based onboarding (teacher sends invite -> auto-login -> forced
    password set) and password login on return visits, isolated from teacher
    auth
  - Forgot/reset-password shared with the teacher flow, generalized to
    students
  - /api/student/schedule never reveals another student's block
  - 24h notice cutoff on change requests
  - Reschedule requests that clash with an existing class auto-deny without
    reaching the teacher's queue
  - Approving a non-clashing request produces the right effect per scope
  - Payment proof upload + teacher review flow
"""
import os
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


STUDENT_PASSWORD = "TestStudent123"


def _latest_invite_token(db, student_id):
    rec = db.student_invites.find_one({"student_id": student_id}, sort=[("created_at", -1)])
    assert rec, "invite record not found"
    return rec["token"]


def _onboard_student(session, db, student, password=STUDENT_PASSWORD):
    """Full first-time flow: teacher sends an invite, the student accepts it
    (auto-login) and is forced to set a password. Returns an authenticated
    requests.Session plus the accept-invite response body."""
    r = session.post(f"{API}/students/{student['id']}/send-portal-invite", json={"channels": ["email"]}, timeout=15)
    assert r.status_code == 200, r.text
    token = _latest_invite_token(db, student["id"])

    s = requests.Session()
    r = s.post(f"{API}/student/auth/accept-invite", json={"token": token}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    s.headers.update({"Authorization": f"Bearer {body['token']}"})

    assert body["must_set_password"] is True
    r2 = s.post(f"{API}/student/auth/set-password", json={"password": password}, timeout=15)
    assert r2.status_code == 200, r2.text
    return s, body


def _login_as_student(email, password=STUDENT_PASSWORD):
    s = requests.Session()
    r = s.post(f"{API}/student/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def student_session(session, db, student, block):
    s, _ = _onboard_student(session, db, student)
    return s


@pytest.fixture(scope="module")
def other_student_session(session, db, other_student, other_block):
    s, _ = _onboard_student(session, db, other_student)
    return s


class TestStudentAuth:
    def test_accept_invite_rejects_bad_token(self):
        r = requests.post(f"{API}/student/auth/accept-invite", json={"token": "not-a-real-token"}, timeout=15)
        assert r.status_code == 400

    def test_invite_token_is_single_use_and_forces_password(self, session, db, other_student):
        # Uses a throwaway student so this doesn't consume/re-onboard the
        # shared `student` fixture other tests depend on.
        r = session.post(f"{API}/students/{other_student['id']}/send-portal-invite",
                          json={"channels": ["email"]}, timeout=15)
        assert r.status_code == 200, r.text
        token = _latest_invite_token(db, other_student["id"])

        r1 = requests.post(f"{API}/student/auth/accept-invite", json={"token": token}, timeout=15)
        assert r1.status_code == 200, r1.text
        assert r1.json()["must_set_password"] is True

        r2 = requests.post(f"{API}/student/auth/accept-invite", json={"token": token}, timeout=15)
        assert r2.status_code == 400

    def test_resending_invite_supersedes_the_previous_one(self, session, db, other_student):
        session.post(f"{API}/students/{other_student['id']}/send-portal-invite",
                      json={"channels": ["email"]}, timeout=15)
        old_token = _latest_invite_token(db, other_student["id"])
        session.post(f"{API}/students/{other_student['id']}/send-portal-invite",
                      json={"channels": ["email"]}, timeout=15)
        r = requests.post(f"{API}/student/auth/accept-invite", json={"token": old_token}, timeout=15)
        assert r.status_code == 400

    def test_student_me(self, student_session, student):
        r = student_session.get(f"{API}/student/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["name"] == student["name"]
        assert r.json()["has_password"] is True

    def test_password_login_works_on_return_visit(self, student_session, student):
        s = _login_as_student(student["email"])
        r = s.get(f"{API}/student/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["name"] == student["name"]

    def test_password_login_rejects_wrong_password(self, student_session, student):
        r = requests.post(f"{API}/student/auth/login",
                           json={"email": student["email"], "password": "wrong-password"}, timeout=15)
        assert r.status_code == 401

    def test_student_token_rejected_on_teacher_routes(self, student_session):
        r = student_session.get(f"{API}/students", timeout=10)
        assert r.status_code == 401

    def test_teacher_token_rejected_on_student_routes(self, session):
        r = session.get(f"{API}/student/me", timeout=10)
        assert r.status_code == 401


class TestStudentPasswordReset:
    def test_forgot_password_is_generic_for_unknown_email(self):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": "nobody-abcxyz@example.com"}, timeout=15)
        assert r.status_code == 200

    def test_forgot_and_reset_password_for_student(self, student_session, db, student):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": student["email"]}, timeout=15)
        assert r.status_code == 200
        rec = db.password_reset_tokens.find_one(
            {"email": student["email"], "account_type": "student"}, sort=[("created_at", -1)],
        )
        assert rec, "student password reset token not found"

        new_password = "NewStudentPass456"
        r2 = requests.post(f"{API}/auth/reset-password",
                            json={"token": rec["token"], "new_password": new_password}, timeout=15)
        assert r2.status_code == 200, r2.text
        assert r2.json()["account_type"] == "student"

        # Old password no longer works, new one does.
        r3 = requests.post(f"{API}/student/auth/login",
                            json={"email": student["email"], "password": STUDENT_PASSWORD}, timeout=15)
        assert r3.status_code == 401
        s = _login_as_student(student["email"], password=new_password)
        assert s.get(f"{API}/student/me", timeout=10).status_code == 200

        # Restore the standard test password so other fixtures/tests keep
        # working — the token above is already spent, so this needs a fresh one.
        requests.post(f"{API}/auth/forgot-password", json={"email": student["email"]}, timeout=15)
        restore_rec = db.password_reset_tokens.find_one(
            {"email": student["email"], "account_type": "student"}, sort=[("created_at", -1)],
        )
        requests.post(f"{API}/auth/reset-password",
                       json={"token": restore_rec["token"], "new_password": STUDENT_PASSWORD}, timeout=15)


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


class TestStudentProgress:
    def test_progress_includes_teacher_notes_and_topics(self, session, student, student_session):
        r = session.post(f"{API}/classes", json={
            "student_id": student["id"], "hours": 1, "class_date": "2025-06-01",
            "notes": "Great improvement on the adavu sequence",
            "topics": ["Alarippu"],
        }, timeout=10)
        assert r.status_code in (200, 201), r.text
        class_id = r.json()["id"]
        try:
            r2 = student_session.get(f"{API}/student/progress", timeout=10)
            assert r2.status_code == 200
            entry = next((c for c in r2.json() if c["id"] == class_id), None)
            assert entry, "class not found in student progress"
            assert entry["notes"] == "Great improvement on the adavu sequence"
            assert entry["topics"] == ["Alarippu"]
        finally:
            session.delete(f"{API}/classes/{class_id}", timeout=10)

    def test_progress_monthly_counts_this_months_class(self, session, student, student_session):
        import datetime
        today = datetime.date.today().isoformat()
        r = session.post(f"{API}/classes", json={
            "student_id": student["id"], "hours": 1.5, "class_date": today,
        }, timeout=10)
        assert r.status_code in (200, 201), r.text
        class_id = r.json()["id"]
        try:
            r2 = student_session.get(f"{API}/student/progress-monthly", params={"months": 3}, timeout=10)
            assert r2.status_code == 200, r2.text
            body = r2.json()
            assert len(body["series"]) == 3
            current_month = body["series"][-1]
            assert current_month["classes"] >= 1
            assert current_month["hours"] >= 1.5
        finally:
            session.delete(f"{API}/classes/{class_id}", timeout=10)


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

    def test_cannot_submit_duplicate_pending_request(self, session, student, student_session):
        # A student re-clicking "Send request" (or opening the form again
        # before hearing back) shouldn't be able to stack a second pending
        # request for the same class.
        b = _far_future_block(session, [student["id"]], day_of_week=6, start_time="18:00", end_time="19:00")
        s = _login_as_student(student["email"])
        try:
            r1 = s.post(f"{API}/student/change-requests", json={
                "block_id": b["id"], "type": "cancel", "scope": "one_time",
            }, timeout=10)
            assert r1.status_code == 200, r1.text
            assert r1.json()["status"] == "pending"

            r2 = s.post(f"{API}/student/change-requests", json={
                "block_id": b["id"], "type": "reschedule", "scope": "one_time",
                "requested_day_of_week": 6, "requested_start_time": "19:00", "requested_end_time": "20:00",
            }, timeout=10)
            assert r2.status_code == 409, r2.text

            # Once the first request is decided, a new one is allowed again.
            deny = session.post(f"{API}/change-requests/{r1.json()['id']}/deny",
                                 json={"reason": "test cleanup"}, timeout=10)
            assert deny.status_code == 200, deny.text
            r3 = s.post(f"{API}/student/change-requests", json={
                "block_id": b["id"], "type": "cancel", "scope": "one_time",
            }, timeout=10)
            assert r3.status_code == 200, r3.text
        finally:
            session.delete(f"{API}/schedule/{b['id']}", timeout=10)

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

    def test_rescheduling_a_reschedule_deletes_the_stale_one_off(self, session, student, student_session):
        # `student_session` isn't used directly — it just guarantees `student`
        # is already onboarded before we log in again below.
        b = _far_future_block(session, [student["id"]], day_of_week=6, start_time="20:00", end_time="21:00")
        s = _login_as_student(student["email"])

        # First reschedule creates one-off #1 and should leave the original
        # recurring block otherwise intact (just skipped for this date).
        r1 = s.post(f"{API}/student/change-requests", json={
            "block_id": b["id"], "type": "reschedule", "scope": "one_time",
            "requested_day_of_week": 6, "requested_start_time": "21:00", "requested_end_time": "22:00",
            "reason": "first move",
        }, timeout=10)
        assert r1.status_code == 200, r1.text
        approve1 = session.post(f"{API}/change-requests/{r1.json()['id']}/approve", timeout=10)
        assert approve1.status_code == 200, approve1.text

        sched = session.get(f"{API}/schedule", timeout=10).json()
        one_off_1 = next((x for x in sched if x["id"] != b["id"] and x["start_time"] == "21:00"), None)
        assert one_off_1, "first one-off not found on the teacher's schedule"
        assert one_off_1["is_one_off"] is True

        # Second reschedule targets the one-off itself (not the original
        # recurring block) — this used to leave one_off_1 dangling forever.
        r2 = s.post(f"{API}/student/change-requests", json={
            "block_id": one_off_1["id"], "type": "reschedule", "scope": "one_time",
            "requested_day_of_week": 6, "requested_start_time": "22:00", "requested_end_time": "23:00",
            "reason": "second move",
        }, timeout=10)
        assert r2.status_code == 200, r2.text
        approve2 = session.post(f"{API}/change-requests/{r2.json()['id']}/approve", timeout=10)
        assert approve2.status_code == 200, approve2.text

        sched_after = session.get(f"{API}/schedule", timeout=10).json()
        ids_after = [x["id"] for x in sched_after]
        assert one_off_1["id"] not in ids_after, "the stale one-off should have been deleted, not left dangling"
        assert any(x["start_time"] == "22:00" for x in sched_after)

        session.delete(f"{API}/schedule/{b['id']}", timeout=10)
        for x in sched_after:
            if x["id"] != b["id"] and x["start_time"] == "22:00":
                session.delete(f"{API}/schedule/{x['id']}", timeout=10)

    def test_permanent_cancel_removes_from_recurring_block(self, session, student, student_session):
        # `student_session` isn't used directly here but ensures `student` has
        # already been onboarded (has a password) before we log in again below.
        b = _far_future_block(session, [student["id"]], day_of_week=4, start_time="10:00", end_time="11:00")
        student_session2 = _login_as_student(student["email"])
        r = student_session2.post(f"{API}/student/change-requests", json={
            "block_id": b["id"], "type": "cancel", "scope": "permanent", "reason": "stopping this slot",
        }, timeout=10)
        assert r.status_code == 200, r.text
        req_id = r.json()["id"]
        r2 = session.post(f"{API}/change-requests/{req_id}/approve", timeout=10)
        assert r2.status_code == 200, r2.text
        r3 = session.get(f"{API}/schedule", timeout=10)
        assert not any(x["id"] == b["id"] for x in r3.json())


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
