"""uil client_purchases: also find a job by the CRM contact person

"What did Divya Raman buy?" / "What did Hadjar buy?" found nothing: those are the CONTACT PERSON on the CRM lead, while the job
stores only the company ("Lakeview Clinic", "Redbull Racing"). The view now joins the job's originating lead and exposes
`contact_name` (the person's NAME only, never phone/email), and `client_key` also covers it, so a person's name finds their
company's jobs. The contact name and its match key are given ONLY to users who hold the CRM module (checked in the database), so
a Workpage-only user cannot learn or probe CRM names through this view.
(New migration instead of editing e9b4c1d7a362, which may already be applied.)

Revision ID: f2c8a5d1e947
Revises: e9b4c1d7a362
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f2c8a5d1e947"
down_revision: Union[str, None] = "e9b4c1d7a362"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL = """
CREATE VIEW uil.client_purchases WITH (security_barrier = true) AS
SELECT c.name::text AS client_name,
       a.name::text AS company_name,
       NULL::text AS contact_name,
       lower(replace(c.name || coalesce(a.name, ''), ' ', ''))::text AS client_key,
       'sales order'::text AS source,
       ('Order ' || to_char(so.order_date, 'YYYY-MM-DD'))::text AS reference,
       p.name::text AS product_name,
       soi.qty::integer AS qty,
       soi.unit_price::numeric AS unit_price,
       (soi.qty * soi.unit_price)::numeric AS line_value,
       so.total::numeric AS deal_value,
       so.status::text AS status,
       so.order_date::date AS date
  FROM public.sales_order_items soi
  JOIN public.sales_orders so ON so.id = soi.order_id
  JOIN public.customers c ON c.id = so.customer_id
  LEFT JOIN public.crm_accounts a ON a.id = c.account_id
  JOIN public.products p ON p.id = soi.product_id
 WHERE so.org_id = uil.current_org() AND uil.can_read(ARRAY['sales'], false)
UNION ALL
SELECT w.client_name::text,
       NULL::text,
       CASE WHEN uil.can_read(ARRAY['crm'], false) THEN l.name END::text,
       lower(replace(w.client_name || CASE WHEN uil.can_read(ARRAY['crm'], false) THEN coalesce(l.name, '') ELSE '' END, ' ', ''))::text,
       'work'::text,
       w.work_number::text,
       p.name::text,
       wi.qty::integer,
       NULL::numeric,
       NULL::numeric,
       round(w.quotation_amount - w.quotation_amount * w.discount_percent / 100, 2)::numeric,
       w.status::text,
       w.created_at::date
  FROM public.work_orders w
  LEFT JOIN public.work_items wi ON wi.work_id = w.id
  LEFT JOIN public.products p ON p.id = wi.product_id
  LEFT JOIN public.crm_leads l ON l.id = w.lead_id
 WHERE w.org_id = uil.current_org() AND w.work_type <> 'sales_order' AND uil.can_read(ARRAY['workpage'], false)
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS uil.client_purchases")     # the column list changed: CREATE OR REPLACE cannot insert a column
    op.execute(SQL)
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'uil_readonly') THEN "
               "GRANT SELECT ON uil.client_purchases TO uil_readonly; END IF; END $$")


def downgrade() -> None:
    pass   # the earlier definition lives in e9b4c1d7a362; downgrading that revision drops the view
