"""
Run this ONCE, manually, before (or right after) deploying the
per-user report subscription change - and never again.

Why this exists: the weekly digest used to be hardcoded to "every user
with the Admin role" - no subscription table existed at all. Every
Admin on every existing org has been getting this email without ever
explicitly opting in, simply because that's how the feature used to
work. If the job switched over to reading the new report_subscriptions
table with no backfill, every one of those existing Admins would
silently stop receiving an email they're already used to getting -
not a crash, just a quiet, confusing regression nobody would notice
until someone asked "why did the weekly summary stop coming?"

This backfill gives every currently-active Admin on every existing org
a real subscription row, preserving today's actual behavior. From this
point forward, new orgs get this automatically at signup (see
app/api/routes/auth.py), and everyone - Admin or not - can subscribe or
unsubscribe for themselves from the Reports page. This script only
ever needs to run once, for the orgs that existed before this feature
did.

Deliberately a STANDALONE script, not an Alembic migration - same
reasoning as grandfather_existing_users.py: a one-time data correction
for accounts that already exist, not a recurring structural need.

Usage:
    cd backend
    $env:DATABASE_URL = "..."          # PowerShell
    python scripts/grandfather_report_subscriptions.py
"""
import os
import sys
import uuid

from sqlalchemy import create_engine, text


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: set DATABASE_URL first (same connection string you use for alembic).", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(database_url)
    with engine.begin() as conn:
        admins_without_subscription = conn.execute(text("""
            SELECT u.id, u.org_id FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE r.name = 'Admin' AND u.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM report_subscriptions rs WHERE rs.user_id = u.id
              )
        """)).fetchall()

        print(f"Active Admins with no subscription row yet: {len(admins_without_subscription)}")

        if not admins_without_subscription:
            print("Nothing to do - every existing Admin already has a subscription row.")
            return

        for user_id, org_id in admins_without_subscription:
            conn.execute(
                text("INSERT INTO report_subscriptions (id, org_id, user_id, created_at) VALUES (:id, :org_id, :user_id, now())"),
                {"id": str(uuid.uuid4()), "org_id": str(org_id), "user_id": str(user_id)},
            )

        print(f"Created {len(admins_without_subscription)} subscription row(s).")

        remaining = conn.execute(text("""
            SELECT count(*) FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE r.name = 'Admin' AND u.status = 'active'
              AND NOT EXISTS (SELECT 1 FROM report_subscriptions rs WHERE rs.user_id = u.id)
        """)).scalar()
        print(f"Active Admins still without a subscription row: {remaining} (should be 0)")
        assert remaining == 0, "Something's wrong - some Admins still have no subscription row after the backfill."

    print("\nDone. Every existing Admin will keep receiving the weekly digest, same as before.")
    print("Anyone can now subscribe or unsubscribe for themselves from the Reports page.")


if __name__ == "__main__":
    main()
