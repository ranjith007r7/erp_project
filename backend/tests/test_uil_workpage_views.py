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


def test_client_purchases_combines_sales_orders_and_jobs_with_space_insensitive_names(client, signup, uil_env, db_session):
    h = signup()
    tag = uuid.uuid4().hex[:6]
    # a direct sale to "Anita<tag>" (like Anita's 5 mounting kits) ...
    cust = client.post("/api/sales/customers", headers=h, json={"name": f"Anita{tag}"}).json()
    prod = client.post("/api/sales/products", headers=h, json={"name": "Mounting kits", "unit_price": 6000, "mrp": 7000}).json()
    quote = client.post("/api/sales/quotations", headers=h, json={"customer_id": cust["id"], "items": [{"product_id": prod["id"], "qty": 5, "unit_price": 6000}]}).json()
    so = client.post(f"/api/sales/quotations/{quote['id']}/accept", headers=h)
    assert so.status_code == 201, so.text
    # ... and a job for "Redbull<tag> Racing" with one product line, plus one with no product lines at all
    w = client.post(W, headers=h, json={"client_name": f"Redbull{tag} Racing", "quotation_amount": 40000, "vendor_amount": 25000}).json()
    client.put(f"{W}/{w['id']}/items", headers=h, json={"items": [{"product_id": prod["id"], "qty": 2}]})
    # a job that came from a CRM lead: the PERSON (Divya Raman) is on the lead, the company (Lakeview) on the job
    lead = client.post("/api/crm/leads", headers=h, json={"name": f"Divya Raman{tag}", "company_name": f"Lakeview{tag} Clinic", "estimated_amount": 30000}).json()
    cv = client.post(f"/api/crm/leads/{lead['id']}/convert", headers=h, json={"opportunity_name": "Clinic fitout", "opportunity_value": 30000})
    assert cv.status_code == 201, cv.text
    org_id = db_session.query(WorkOrder.org_id).filter(WorkOrder.client_name == f"Redbull{tag} Racing").scalar()

    def ask(where, modules=("sales", "workpage")):
        return _ask(db_session, org_id, f"SELECT source, reference, product_name, qty FROM client_purchases WHERE client_key LIKE '{where}'", modules).rows

    assert [(r[0], r[2], r[3]) for r in ask(f"%anita{tag}%")] == [("sales order", "Mounting kits", 5)]
    for spelling in (f"%redbull{tag}racing%", f"%redbull{tag}%"):                    # 'Red Bull' vs 'Redbull' no longer matters
        rows = ask(spelling)
        assert [(r[0], r[2], r[3]) for r in rows] == [("work", "Mounting kits", 2)]
    crm = ("sales", "workpage", "crm")
    assert [(r[0], r[2]) for r in ask(f"%divyaraman{tag}%", crm)] == [("work", None)]       # by PERSON (needs the CRM module too)
    assert ask(f"%divyaraman{tag}%") == []                                                 # ... but not for someone without CRM access
    for key in (f"%lakeview{tag}clinic%", f"%lakeview{tag}%"):                             # by company: Workpage is enough
        assert [(r[0], r[2]) for r in ask(key)] == [("work", None)]                        # a job with no product lines still shows
    # each branch is gated by its own module, inside the database
    assert [r[0] for r in ask(f"%anita{tag}%", ("sales",))] == ["sales order"] and ask(f"%redbull{tag}%", ("sales",)) == []
    assert ask(f"%anita{tag}%", ("workpage",)) == [] and len(ask(f"%redbull{tag}%", ("workpage",))) == 1
    assert ask(f"%anita{tag}%", ("hr",)) == []


def test_person_name_is_hidden_without_crm_access_and_contact_questions_get_a_work_number_hint(client, signup, uil_env, db_session):
    from app.services.intelligence import pipeline as pl
    from app.services.intelligence.access import AccessProfile
    from uil_helpers import FakeLLM

    h = signup()
    tag = uuid.uuid4().hex[:6]
    lead = client.post("/api/crm/leads", headers=h, json={"name": f"Hadjar{tag}", "company_name": f"Redbull{tag} Racing", "phone": "9876543210", "estimated_amount": 48000}).json()
    assert client.post(f"/api/crm/leads/{lead['id']}/convert", headers=h, json={"opportunity_name": "Race car", "opportunity_value": 48000}).status_code == 201
    org_id = db_session.query(WorkOrder.org_id).filter(WorkOrder.client_name == f"Redbull{tag} Racing").scalar()
    work_no = db_session.query(WorkOrder.work_number).filter(WorkOrder.client_name == f"Redbull{tag} Racing").scalar()
    q = f"SELECT client_name, contact_name FROM client_purchases WHERE client_key LIKE '%hadjar{tag}%'"
    assert _ask(db_session, org_id, q, ("workpage", "crm")).rows[0][1] == f"Hadjar{tag}"
    assert _ask(db_session, org_id, q, ("workpage",)).rows == []                       # no CRM module: the person's name is neither shown nor searchable
    assert _ask(db_session, org_id, f"SELECT contact_name FROM client_purchases WHERE client_key LIKE '%redbull{tag}%'", ("workpage",)).rows[0][0] is None

    # a "client details" question is still refused, but the answer says where to look and gives the work number only
    access = AccessProfile(modules=frozenset({"workpage", "crm", "sales"}), restricted=False)
    r = pl.answer_question(db_session, str(org_id), f"List the client details of Redbull{tag} Racing", None, FakeLLM(gate="NO", sql="SELECT 1"), access)
    assert not r.answered and r.stage == pl.REFUSED_SCOPE and r.sql is None
    assert "can't answer that one" in r.answer and work_no in r.answer and "search bar" in r.answer
    assert "9876543210" not in r.answer and r.rows == []                                # no phone, no table, nothing personal
    # an unrelated refusal gets no hint
    r2 = pl.answer_question(db_session, str(org_id), "Who won the F1 championship?", None, FakeLLM(gate="NO", sql="SELECT 1"), access)
    assert r2.answer == pl.REFUSAL_TEXT
