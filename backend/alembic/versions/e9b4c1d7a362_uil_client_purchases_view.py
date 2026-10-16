"""uil view: client_purchases (one place to ask "what did <client> buy?")

The AI had to guess between sales_orders (direct sales) and work_orders (jobs from CRM conversions) and kept picking one,
so "what did Anita buy?" and "what did Redbull Racing buy?" could not both work. This view unions both, one row per
product line (a job with no product lines still shows once, so its deal is visible), plus `client_key` = the client's
name lower-cased with spaces removed, so 'Redbull Racing' / 'Red Bull Racing' / 'redbull' all match the same LIKE.

Each branch checks its own module in the database (uil.can_read): sales-only users see only sales lines,
workpage-only users see only job lines. Frozen copy of the manifest entry; tests/test_uil_manifest.py guards drift.

Revision ID: e9b4c1d7a362
Revises: d7a3f9c2b518
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e9b4c1d7a362"
down_revision: Union[str, None] = "d7a3f9c2b518"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL = """
CREATE VIEW uil.client_purchases WITH (security_barrier = true) AS
SELECT c.name::text AS client_name,
       a.name::text AS company_name,
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
       lower(replace(w.client_name, ' ', ''))::text,
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
 WHERE w.org_id = uil.current_org() AND w.work_type <> 'sales_order' AND uil.can_read(ARRAY['workpage'], false)
"""


def upgrade() -> None:
    op.execute(SQL)
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'uil_readonly') THEN "
               "GRANT SELECT ON uil.client_purchases TO uil_readonly; END IF; END $$")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS uil.client_purchases")
