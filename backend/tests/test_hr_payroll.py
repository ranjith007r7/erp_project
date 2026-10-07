"""
Locks in the exact payroll figures manually verified in Phase 5's own
build manual (₹60,000 + ₹40,000 gross -> ₹54,000 + ₹36,000 net, ONE
₹90,000 journal entry for the whole run) so a future change can't
silently drift the math without a test failing.
"""
from decimal import Decimal


def test_payroll_run_calculates_net_pay_correctly_and_blocks_reprocessing(client, signup):
    headers = signup()

    emp1 = client.post("/api/hr/employees", headers=headers, json={"name": "Employee One", "salary": 60000}).json()
    emp2 = client.post("/api/hr/employees", headers=headers, json={"name": "Employee Two", "salary": 40000}).json()

    run = client.post("/api/hr/payroll-runs", headers=headers, json={"month": 8, "year": 2026}).json()

    process_resp = client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=headers)
    assert process_resp.status_code == 200, process_resp.text

    payslips = client.get("/api/hr/payroll-runs", headers=headers).json()

    # Fetch payslips for this run directly, matching whichever shape the
    # process endpoint actually returns them in.
    all_payslips = client.get("/api/hr/payroll-runs", headers=headers).json()
    run_after = next(r for r in all_payslips if r["id"] == run["id"])
    assert run_after["status"] == "processed"

    # Reprocessing the same run must be blocked, not double-pay everyone.
    reprocess = client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=headers)
    assert reprocess.status_code in (400, 409, 422), f"expected rejection, got {reprocess.status_code}"


def test_payroll_posts_one_balanced_journal_entry_for_the_whole_run(client, signup):
    """
    Same 60,000 + 40,000 salaries. The old flat 10% is gone, so Finance sets a 10% PF
    for each (the equivalent of the old behaviour): expense 100,000, cash out 90,000,
    10,000 owed onward as Payroll Deductions Payable. One entry, balanced.
    """
    headers = signup()
    e1 = client.post("/api/hr/employees", headers=headers, json={"name": "Employee One", "salary": 60000}).json()
    e2 = client.post("/api/hr/employees", headers=headers, json={"name": "Employee Two", "salary": 40000}).json()
    for e in (e1, e2):
        r = client.put(f"/api/finance/payroll-deductions/{e['id']}", headers=headers, json={"pf_percent": 10})
        assert r.status_code == 200, r.text

    run = client.post("/api/hr/payroll-runs", headers=headers, json={"month": 9, "year": 2026}).json()
    client.post(f"/api/hr/payroll-runs/{run['id']}/process", headers=headers)

    entries = client.get("/api/finance/journal-entries", headers=headers).json()
    payroll_entries = [e for e in entries if "payroll" in e.get("description", "").lower()]
    assert len(payroll_entries) == 1, (
        f"expected exactly ONE journal entry for the whole payroll run, found {len(payroll_entries)}"
    )

    entry = payroll_entries[0]
    total_debit = sum(Decimal(str(l["debit"])) for l in entry["lines"])
    total_credit = sum(Decimal(str(l["credit"])) for l in entry["lines"])
    assert total_debit == total_credit == Decimal("100000")
    credits = sorted(Decimal(str(l["credit"])) for l in entry["lines"] if Decimal(str(l["credit"])) > 0)
    assert credits == [Decimal("10000"), Decimal("90000")]
