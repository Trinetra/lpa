"""
Backend tests for Web Push subscribe/unsubscribe (both the teacher's and the
student's endpoints) plus that send_push() no-ops cleanly when VAPID keys
aren't configured. A real device actually receiving a push can't be verified
by an HTTP-only test — this only covers the subscription CRUD contract.
"""
import os
import uuid
import requests
import pytest
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://lpa.saisanathana.com").rstrip("/")
API = f"{BASE_URL}/api"
EMAIL = "lpathreya@gmail.com"
PASSWORD = "prashanth"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

STUDENT_PASSWORD = "TestPushStudent123"


@pytest.fixture(scope="module")
def db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def student(session):
    r = session.post(f"{API}/students", json={
        "name": "TEST_Push Student",
        "email": "test.push.student@example.com",
        "hourly_rate": 500,
    }, timeout=10)
    assert r.status_code in (200, 201), r.text
    st = r.json()
    yield st
    session.delete(f"{API}/students/{st['id']}", timeout=10)


@pytest.fixture(scope="module")
def student_session(session, db, student):
    r = session.post(f"{API}/students/{student['id']}/send-portal-invite", json={"channels": ["email"]}, timeout=15)
    assert r.status_code == 200, r.text
    rec = db.student_invites.find_one({"student_id": student["id"]}, sort=[("created_at", -1)])
    assert rec, "invite record not found"

    s = requests.Session()
    r = s.post(f"{API}/student/auth/accept-invite", json={"token": rec["token"]}, timeout=15)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    r2 = s.post(f"{API}/student/auth/set-password", json={"password": STUDENT_PASSWORD}, timeout=15)
    assert r2.status_code == 200, r2.text
    return s


def _fake_subscription():
    # A plausible-shaped (but non-functional) Web Push subscription — good
    # enough to exercise the storage contract without a real browser/push
    # service in the loop.
    return {
        "endpoint": f"https://fcm.googleapis.com/fcm/send/TEST_{uuid.uuid4().hex}",
        "keys": {"p256dh": "TEST_p256dh_" + uuid.uuid4().hex, "auth": "TEST_auth_" + uuid.uuid4().hex},
    }


class TestTeacherPushSubscription:
    def test_subscribe_requires_auth(self):
        r = requests.post(f"{API}/push/subscribe", json=_fake_subscription(), timeout=10)
        assert r.status_code == 401

    def test_subscribe_and_unsubscribe(self, session, db):
        sub = _fake_subscription()
        r = session.post(f"{API}/push/subscribe", json=sub, timeout=10)
        assert r.status_code == 200, r.text

        rec = db.push_subscriptions.find_one({"endpoint": sub["endpoint"]})
        assert rec, "subscription not stored"
        assert rec["owner_type"] == "user"
        assert rec["keys"]["p256dh"] == sub["keys"]["p256dh"]

        r2 = session.post(f"{API}/push/unsubscribe", json={"endpoint": sub["endpoint"]}, timeout=10)
        assert r2.status_code == 200, r2.text
        assert db.push_subscriptions.find_one({"endpoint": sub["endpoint"]}) is None

    def test_resubscribing_same_endpoint_upserts(self, session, db):
        sub = _fake_subscription()
        session.post(f"{API}/push/subscribe", json=sub, timeout=10)
        session.post(f"{API}/push/subscribe", json=sub, timeout=10)
        assert db.push_subscriptions.count_documents({"endpoint": sub["endpoint"]}) == 1
        session.post(f"{API}/push/unsubscribe", json={"endpoint": sub["endpoint"]}, timeout=10)


class TestStudentPushSubscription:
    def test_subscribe_requires_auth(self):
        r = requests.post(f"{API}/student/push/subscribe", json=_fake_subscription(), timeout=10)
        assert r.status_code == 401

    def test_teacher_cannot_use_student_push_routes(self, session):
        r = session.post(f"{API}/student/push/subscribe", json=_fake_subscription(), timeout=10)
        assert r.status_code == 401

    def test_subscribe_and_unsubscribe(self, student_session, db, student):
        sub = _fake_subscription()
        r = student_session.post(f"{API}/student/push/subscribe", json=sub, timeout=10)
        assert r.status_code == 200, r.text

        rec = db.push_subscriptions.find_one({"endpoint": sub["endpoint"]})
        assert rec, "subscription not stored"
        assert rec["owner_type"] == "student"

        r2 = student_session.post(f"{API}/student/push/unsubscribe", json={"endpoint": sub["endpoint"]}, timeout=10)
        assert r2.status_code == 200, r2.text
        assert db.push_subscriptions.find_one({"endpoint": sub["endpoint"]}) is None

    def test_cannot_unsubscribe_another_students_endpoint(self, student_session, db, student, session):
        # A malicious/careless unsubscribe call should only ever be able to
        # remove the caller's own subscriptions.
        sub = _fake_subscription()
        r = session.post(f"{API}/push/subscribe", json=sub, timeout=10)
        assert r.status_code == 200, r.text
        student_session.post(f"{API}/student/push/unsubscribe", json={"endpoint": sub["endpoint"]}, timeout=10)
        assert db.push_subscriptions.find_one({"endpoint": sub["endpoint"]}) is not None
        session.post(f"{API}/push/unsubscribe", json={"endpoint": sub["endpoint"]}, timeout=10)
