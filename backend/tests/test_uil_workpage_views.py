"""The AI can see Workpage data (jobs, parts, payments), only for people who hold the Workpage module, and only their own org."""
import uuid

from app.models.workpage import WorkOrder
from app.services.intelligence.executor import run_readonly_query

W = "/api/workpage/works"


def _ask(db, org_id, sql, modules):
    return run_readonly_query(db, str(org_id), sql, max_rows=50, timeout_ms=5000, modules=modules)


def test_ai_can_read_a_clients_job_parts_and_payments(client, signup, uil_env, db_session):
    h = signup()
    tag = "Redbull" + uuid.uuid4().hex[:5]
    prod = client.post("/api/sales/products", headers=h, json={"name": "Mounting kits", "unit_price": 6000, "mrp": 7000}).json()
    w = client.post(W, headers=h, json={"client_name": tag + " Racing", "quotation_amount": 40000, "vendor_amount": 25000, "discount_percent": 0}).json()
    client.post(f"{W}/{w['id']}/payments", headers=h, json={"amount": 5000, "method": "cash"})
    org_id = db_session.query(WorkOrder.org_id).filter(WorkOrder.client_name == tag + " Racing").scalar()
    assert org_id

    r = _ask(db_session, org_id, f"SELECT work_number, client_name, quotation_amount - vendor_amount AS profit FROM work_orders WHERE client_name ILIKE '%{tag}%'", ("workpage",))
    assert len(r.rows) == 1 and float(r.rows[0][2]) == 15000
    p = _ask(db_session, org_id, f"SELECT SUM(p.amount) FROM work_payments p JOIN work_orders w ON w.id = p.work_id WHERE w.client_name ILIKE '%{tag}%'", ("workpage",))
    assert float(p.rows[0][0]) == 5000


def test_workpage_views_need_the_workpage_module_and_stay_inside_the_org(client, signup, uil_env, db_session):
    h = signup()
    tag = "Hadjar" + uuid.uuid4().hex[:5]
    client.post(W, headers=h, json={"client_name": tag, "quotation_amount": 1000})
    org_id = db_session.query(WorkOrder.org_id).filter(WorkOrder.client_name == tag).scalar()
    q = f"SELECT client_name FROM work_orders WHERE client_name = '{tag}'"
    assert len(_ask(db_session, org_id, q, ("workpage",)).rows) == 1
    assert _ask(db_session, org_id, q, ("sales", "finance", "crm")).rows == []          # no Workpage module -> zero rows
    other = signup()
    other_org = db_session.query(WorkOrder.org_id).filter(WorkOrder.client_name == tag).scalar()
    from app.models.organization import Organization
    some_other = db_session.query(Organization.id).filter(Organization.id != other_org).first()[0]
    assert _ask(db_session, some_other, q, ("workpage",)).rows == []                    # another tenant never sees it
