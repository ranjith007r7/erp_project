import requests
import threading
import uuid

BASE = "http://127.0.0.1:8001"
unique = uuid.uuid4().hex[:8]

signup = requests.post(f"{BASE}/api/auth/signup", json={
    "org_name": f"Concurrency Check {unique}", "subdomain": f"concurcheck{unique}",
    "admin_name": "Admin A", "admin_email": f"admina{unique}@concurrencycheck.com", "admin_password": "testpass123",
}).json()
auth_a = {"Authorization": f"Bearer {signup['access_token']}"}
me_a = requests.get(f"{BASE}/api/auth/me", headers=auth_a).json()

second_role = requests.post(f"{BASE}/api/core/roles", headers=auth_a, json={"name": "Second Admin"}).json()
requests.post(f"{BASE}/api/core/roles/{second_role['id']}/permissions", headers=auth_a, json={"module": "core", "action": "manage_access"})
requests.post(f"{BASE}/api/core/users", headers=auth_a, json={"name": "Admin B", "email": f"adminb{unique}@concurrencycheck.com", "password": "testpass123", "role_id": second_role["id"]})
login_b = requests.post(f"{BASE}/api/auth/login", json={"email": f"adminb{unique}@concurrencycheck.com", "password": "testpass123"}).json()
auth_b = {"Authorization": f"Bearer {login_b['access_token']}"}
me_b = requests.get(f"{BASE}/api/auth/me", headers=auth_b).json()

powerless = requests.post(f"{BASE}/api/core/roles", headers=auth_a, json={"name": "Powerless"}).json()

print(f"Org has 2 real admins: A={me_a['id']}, B={me_b['id']}")
print("Firing two GENUINELY separate HTTP requests at the same instant...")

results = {}
def demote(name, auth, target_id):
    r = requests.patch(f"{BASE}/api/core/users/{target_id}/role", headers=auth, json={"role_id": powerless["id"]})
    results[name] = r.status_code

t1 = threading.Thread(target=demote, args=("A_demotes_B", auth_a, me_b["id"]))
t2 = threading.Thread(target=demote, args=("B_demotes_A", auth_b, me_a["id"]))
t1.start(); t2.start()
t1.join(); t2.join()

print("Results:", results)
if 400 in results.values() and 200 in results.values():
    print("CORRECT: one succeeded, one was properly rejected. The security guard held.")
else:
    print("UNEXPECTED — worth a closer look:", results)