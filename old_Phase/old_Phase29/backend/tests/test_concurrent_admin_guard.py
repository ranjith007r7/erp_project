"""
Locks in a real finding from an adversarial re-test pass: two genuinely
simultaneous requests, each an admin-equivalent user trying to demote
the OTHER, could theoretically both pass the last-admin guard's check
before either commits (a TOCTOU race), if nothing serializes them.
Fixed with a real Postgres advisory lock (see
app.api.deps.lock_org_for_admin_guard), not just trusted because one
manual concurrency test happened to pass.

This test uses real Python threads against the TestClient - not a
perfect substitute for true multi-process concurrency, but exercises
the same code path and locking behavior the manual attack did.
"""
import threading


def test_concurrent_mutual_demotion_cannot_leave_zero_admins(client, signup):
    admin = signup()
    me_a = client.get("/api/auth/me", headers=admin).json()

    second_role = client.post("/api/core/roles", headers=admin, json={"name": "Second Admin"}).json()
    client.post(f"/api/core/roles/{second_role['id']}/permissions", headers=admin, json={"module": "core", "action": "manage_access"})
    client.post("/api/core/users", headers=admin, json={
        "name": "Admin B", "email": "adminb-concurrent@test.com", "password": "testpass123", "role_id": second_role["id"],
    })
    login_b = client.post("/api/auth/login", json={"email": "adminb-concurrent@test.com", "password": "testpass123"}).json()
    auth_b = {"Authorization": f"Bearer {login_b['access_token']}"}
    me_b = client.get("/api/auth/me", headers=auth_b).json()

    powerless = client.post("/api/core/roles", headers=admin, json={"name": "Powerless"}).json()

    results = {}

    def demote(name, auth, target_id):
        resp = client.patch(f"/api/core/users/{target_id}/role", headers=auth, json={"role_id": powerless["id"]})
        results[name] = resp.status_code

    t1 = threading.Thread(target=demote, args=("A_demotes_B", admin, me_b["id"]))
    t2 = threading.Thread(target=demote, args=("B_demotes_A", auth_b, me_a["id"]))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # The real invariant: regardless of which request "won", exactly one
    # of them must have been rejected - both succeeding would mean both
    # admins got demoted simultaneously, leaving zero.
    assert 400 in results.values(), f"expected one request to be rejected by the last-admin guard, got {results}"
    assert 200 in results.values(), f"expected the other request to succeed, got {results}"

    from app.core.database import SessionLocal
    from app.models.user import User
    from app.models.role import Role, Permission

    db = SessionLocal()
    try:
        count = (
            db.query(User)
            .join(Role, User.role_id == Role.id)
            .join(Permission, Permission.role_id == Role.id)
            .filter(
                User.org_id == me_a["org_id"], User.status == "active",
                Permission.module == "core", Permission.action == "manage_access",
            )
            .count()
        )
        assert count >= 1, "a concurrent mutual-demotion attempt must never leave zero admin-equivalent users"
    finally:
        db.close()
