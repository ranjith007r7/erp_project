"""Per-employee PF / insurance / TDS percentages and unpaid-leave days, entered by Finance."""
from decimal import Decimal

from test_procurement_workflow import make_user

D = Decimal


def emp(client, h, name="E", salary=30000):
    return client.post("/api/hr/employees", headers=h, json={"name": name, "salary": salary}).json()


def run_for(client, h, month=10, year=2026):
    return client.post("/api/hr/payroll-runs", headers=h, json={"month": month, "year": year}).json()


def slip(client, h, run_id, employee_id):
    r = next(x for x in client.get("/api/hr/payroll-runs", headers=h).json() if x["id"] == run_id)
    return next(p for p in r["payslips"] if p["employee_id"] == employee_id)


def test_percentages_become_exact_rupee_amounts(client, signup):
    h = signup()
    e = emp(client, h, salary=50000)
    client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=h, json={"pf_percent": 12, "insurance_percent": 2.5, "tds_percent": 5})
    run = run_for(client, h)
    r = client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h)
    assert r.status_code == 200 and r.json()["employees_without_deductions"] == 0
    p = slip(client, h, run["id"], e["id"])
    assert (D(p["pf_amount"]), D(p["insurance_amount"]), D(p["tds_amount"])) == (D("6000"), D("1250"), D("2500"))
    assert D(p["deductions"]) == D("9750") and D(p["net_pay"]) == D("40250") and D(p["leave_deduction"]) == 0
    assert (D(p["pf_percent"]), D(p["tds_percent"])) == (D("12"), D("5"))


def test_unpaid_leave_days_cut_salary_per_day_of_that_month(client, signup):
    h = signup()
    e = emp(client, h, salary=31000)           # October has 31 days -> 1000/day
    run = run_for(client, h, 10, 2026)
    r = client.put(f"/api/finance/payroll-runs/{run['id']}/lop/{e['id']}", headers=h, json={"lop_days": 2.5})
    assert r.status_code == 200
    client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h)
    p = slip(client, h, run["id"], e["id"])
    assert D(p["lop_days"]) == D("2.5") and D(p["leave_deduction"]) == D("2500") and D(p["net_pay"]) == D("28500")
    # February (28 days) has a different per-day rate
    e2 = emp(client, h, "F", salary=28000)
    run2 = run_for(client, h, 2, 2027)
    client.put(f"/api/finance/payroll-runs/{run2['id']}/lop/{e2['id']}", headers=h, json={"lop_days": 1})
    client.post(f"/api/hr/payroll-runs/{run2['id']}/process", headers=h)
    assert D(slip(client, h, run2["id"], e2["id"])["leave_deduction"]) == D("1000")


def test_journal_entry_balances_with_every_kind_of_deduction(client, signup):
    h = signup()
    e = emp(client, h, salary=31000)
    client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=h, json={"pf_percent": 10, "tds_percent": 5})
    run = run_for(client, h)
    client.put(f"/api/finance/payroll-runs/{run['id']}/lop/{e['id']}", headers=h, json={"lop_days": 1})
    client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h)
    entry = [x for x in client.get("/api/finance/journal-entries", headers=h).json() if "payroll" in x["description"].lower()][0]
    accounts = {a["id"]: a["name"] for a in client.get("/api/finance/accounts", headers=h).json()}
    lines = {accounts[l["account_id"]]: (D(l["debit"]), D(l["credit"])) for l in entry["lines"]}
    # gross 31000, unpaid leave 1000, PF 3100, TDS 1550 -> net 25350
    assert lines["Payroll Expense"] == (D("30000"), D("0"))              # earned pay only
    assert lines["Cash"] == (D("0"), D("25350"))
    assert lines["Payroll Deductions Payable"] == (D("0"), D("4650"))    # PF + TDS owed onward
    assert sum(d for d, _ in lines.values()) == sum(c for _, c in lines.values())


def test_employee_without_a_profile_is_paid_in_full_and_flagged(client, signup):
    h = signup()
    a, b = emp(client, h, "A", 20000), emp(client, h, "B", 10000)
    client.put(f"/api/finance/payroll-deductions/{a['id']}", headers=h, json={"pf_percent": 12})
    run = run_for(client, h)
    r = client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h).json()
    assert r["employees_without_deductions"] == 1
    assert D(slip(client, h, run["id"], b["id"])["net_pay"]) == D("10000")


def test_deductions_list_shows_who_is_configured_and_suggests_lop_from_approved_leave(client, signup):
    h = signup()
    a, b = emp(client, h, "A", 20000), emp(client, h, "B", 10000)
    client.put(f"/api/finance/payroll-deductions/{a['id']}", headers=h, json={"pf_percent": 12})
    lv = client.post("/api/hr/leave-requests", headers=h, json={"employee_id": b["id"], "leave_type": "Loss of Pay (Unpaid)", "start_date": "2026-10-05", "end_date": "2026-10-07"}).json()
    client.patch(f"/api/hr/leave-requests/{lv['id']}/status", headers=h, json={"status": "approved"})
    paid = client.post("/api/hr/leave-requests", headers=h, json={"employee_id": b["id"], "leave_type": "Casual Leave", "start_date": "2026-10-10", "end_date": "2026-10-11"}).json()
    client.patch(f"/api/hr/leave-requests/{paid['id']}/status", headers=h, json={"status": "approved"})
    run = run_for(client, h)
    rows = {r["name"]: r for r in client.get("/api/finance/payroll-deductions", headers=h, params={"run_id": run["id"]}).json()}
    assert rows["A"]["configured"] and not rows["B"]["configured"]
    assert D(rows["B"]["lop_days"]) == 3            # only the unpaid type counts; the 2 casual days do not
    client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h)
    assert D(slip(client, h, run["id"], b["id"])["leave_deduction"]) == (D("10000") / 31 * 3).quantize(D("0.01"))


def test_validation_limits(client, signup):
    h = signup()
    e = emp(client, h)
    put = lambda body: client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=h, json=body)
    assert put({"pf_percent": 101}).status_code == 422
    assert put({"pf_percent": -1}).status_code == 422
    assert put({"pf_percent": 60, "insurance_percent": 30, "tds_percent": 20}).status_code == 400
    run = run_for(client, h, 2, 2027)
    lop = lambda d: client.put(f"/api/finance/payroll-runs/{run['id']}/lop/{e['id']}", headers=h, json={"lop_days": d})
    assert lop(-1).status_code == 422 and lop(29).status_code == 400 and lop(28).status_code == 200


def test_net_pay_never_goes_negative_and_journal_still_balances(client, signup):
    h = signup()
    e = emp(client, h, salary=30000)
    client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=h, json={"pf_percent": 50, "insurance_percent": 25, "tds_percent": 20})
    run = run_for(client, h, 9, 2026)        # 30 days
    client.put(f"/api/finance/payroll-runs/{run['id']}/lop/{e['id']}", headers=h, json={"lop_days": 20})
    client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h)
    p = slip(client, h, run["id"], e["id"])
    assert D(p["net_pay"]) >= 0 and D(p["gross"]) == D(p["net_pay"]) + D(p["deductions"])
    entry = [x for x in client.get("/api/finance/journal-entries", headers=h).json() if "payroll" in x["description"].lower()][0]
    assert sum(D(l["debit"]) for l in entry["lines"]) == sum(D(l["credit"]) for l in entry["lines"])


def test_processed_run_locks_lop_and_permissions_are_finance_based(client, signup):
    h = signup()
    e = emp(client, h)
    run = run_for(client, h)
    client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=h)
    assert client.put(f"/api/finance/payroll-runs/{run['id']}/lop/{e['id']}", headers=h, json={"lop_days": 1}).status_code == 400
    viewer = make_user(client, h, [("finance", "view")])
    editor = make_user(client, h, [("finance", "view"), ("finance", "edit")])
    hr_only = make_user(client, h, [("hr", "view"), ("hr", "create"), ("hr", "edit")])
    body = {"pf_percent": 12}
    assert client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=viewer, json=body).status_code == 403
    assert client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=hr_only, json=body).status_code == 403
    assert client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=editor, json=body).status_code == 200
    assert client.get("/api/finance/payroll-deductions", headers=viewer).status_code == 200


def test_org_isolation_of_deductions(client, signup):
    a, b = signup(), signup()
    e = emp(client, a)
    run = run_for(client, a)
    assert client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=b, json={"pf_percent": 5}).status_code == 404
    assert client.put(f"/api/finance/payroll-runs/{run['id']}/lop/{e['id']}", headers=b, json={"lop_days": 1}).status_code == 404
    assert client.get("/api/finance/payroll-deductions", headers=b).json() == []


def test_leave_legend_has_standard_types_and_unpaid_one(client, signup):
    h = signup()
    types = {t["code"]: t for t in client.get("/api/hr/leave-types", headers=h).json()}
    assert {"CL", "SL", "EL", "ML", "PL", "LOP"} <= set(types)
    assert float(types["SL"]["per_month"]) == 1 and float(types["SL"]["days_per_year"]) == 12
    assert types["LOP"]["paid"] is False and types["CL"]["paid"] is True
    assert [t["code"] for t in client.get("/api/finance/leave-types", headers=h).json()] == [t["code"] for t in client.get("/api/hr/leave-types", headers=h).json()]
    r = client.patch(f"/api/hr/leave-types/{types['CL']['id']}", headers=h, json={"days_per_year": 10})
    assert r.status_code == 200 and float(r.json()["days_per_year"]) == 10


def test_finance_can_list_payroll_runs_without_hr_access(client, signup):
    h = signup()
    run = run_for(client, h)
    finance_only = make_user(client, h, [("finance", "view")])
    assert client.get("/api/hr/payroll-runs", headers=finance_only).status_code == 403
    runs = client.get("/api/finance/payroll-runs", headers=finance_only).json()
    assert [r["id"] for r in runs] == [run["id"]] and runs[0]["status"] == "draft"
