"""
Regression tests for per-user report subscriptions - the real behaviors
proven manually during development, captured here so they can never
silently regress. See app/models/reports.py's ReportSubscription
docstring for the design reasoning.
"""


def test_signup_auto_subscribes_the_creating_admin(client, signup):
    admin = signup()
    resp = client.get("/api/reports/subscription", headers=admin)
    assert resp.json() == {"subscribed": True}


def test_unsubscribe_then_resubscribe(client, signup):
    admin = signup()
    resp = client.delete("/api/reports/subscription", headers=admin)
    assert resp.status_code == 204
    assert client.get("/api/reports/subscription", headers=admin).json() == {"subscribed": False}

    resp = client.post("/api/reports/subscription", headers=admin)
    assert resp.status_code == 201
    assert client.get("/api/reports/subscription", headers=admin).json() == {"subscribed": True}


def test_unsubscribe_is_idempotent(client, signup):
    """Unsubscribing when already unsubscribed must not error - same as clicking a toggle twice."""
    admin = signup()
    client.delete("/api/reports/subscription", headers=admin)
    resp = client.delete("/api/reports/subscription", headers=admin)
    assert resp.status_code == 204


def test_subscribe_is_idempotent(client, signup):
    """Subscribing when already subscribed must not create a duplicate row or error."""
    admin = signup()
    resp = client.post("/api/reports/subscription", headers=admin)
    assert resp.status_code == 201
    assert client.get("/api/reports/subscription", headers=admin).json() == {"subscribed": True}


def test_non_admin_can_subscribe(client, signup):
    """
    The core design point: this is a personal preference, not an access-
    control decision - any logged-in user can opt in, regardless of role.
    """
    import uuid
    admin = signup()
    role = client.post("/api/core/roles", headers=admin, json={"name": "Restricted Role"}).json()
    client.post(f"/api/core/roles/{role['id']}/permissions", headers=admin, json={"module": "sales", "action": "view"})
    email = f"nonadmin-{uuid.uuid4().hex[:8]}@test.com"
    client.post("/api/core/users", headers=admin, json={"name": "Non Admin", "email": email, "password": "testpass123", "role_id": role["id"]})
    login = client.post("/api/auth/login", json={"email": email, "password": "testpass123"}).json()
    non_admin = {"Authorization": f"Bearer {login['access_token']}"}

    resp = client.post("/api/reports/subscription", headers=non_admin)
    assert resp.status_code == 201
    assert client.get("/api/reports/subscription", headers=non_admin).json() == {"subscribed": True}


def test_weekly_digest_respects_unsubscribe(client, signup, monkeypatch):
    """
    The real proof this feature exists for: an Admin who unsubscribes
    must receive zero digest emails for their org, even though the old
    hardcoded behavior would have sent them one unconditionally.

    Measures the DELTA across calls within this one test, rather than
    asserting an absolute count - the digest job processes every org in
    the whole test database, including ones other tests create via
    signup(), so an absolute "digests_sent == 0" would be fragile and
    wrong the moment this suite has more than one org in it.
    """
    from app.core.config import settings
    monkeypatch.setattr(settings, "CRON_SECRET", "test_secret_for_jobs")
    headers = {"X-Cron-Secret": "test_secret_for_jobs"}

    baseline = client.post("/api/internal/jobs/weekly-digest", headers=headers).json()["digests_sent"]

    admin = signup()  # auto-subscribes this new org's admin
    with_new_org = client.post("/api/internal/jobs/weekly-digest", headers=headers).json()["digests_sent"]
    assert with_new_org == baseline + 1, "the newly-signed-up, auto-subscribed org should add exactly one digest"

    client.delete("/api/reports/subscription", headers=admin)
    after_unsubscribe = client.post("/api/internal/jobs/weekly-digest", headers=headers).json()["digests_sent"]
    assert after_unsubscribe == baseline, "unsubscribing should remove exactly this org's digest, back to baseline"
