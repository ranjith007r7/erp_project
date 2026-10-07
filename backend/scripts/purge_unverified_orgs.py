"""
Deletes organizations whose admin never verified their email within N days (sign-up spam).
Safe by default: prints what it would delete; pass --yes to actually do it.

Usage (from backend/):
    python scripts/purge_unverified_orgs.py --days 7          # dry run
    python scripts/purge_unverified_orgs.py --days 7 --yes    # delete
Run it from a daily scheduled job (Render cron) to keep the database clean.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.org_data import delete_organization  # noqa: E402
from app.services.storage import delete_org_files  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    cutoff = datetime.utcnow() - timedelta(days=args.days)
    db = SessionLocal()
    try:
        orgs = db.query(Organization).filter(Organization.created_at < cutoff).all()
        doomed = []
        for org in orgs:
            verified = db.query(func.count(User.id)).filter(User.org_id == org.id, User.email_verified.is_(True)).scalar()
            if not verified:
                doomed.append(org)
        for org in doomed:
            print(("DELETING " if args.yes else "would delete ") + f"{org.name} ({org.subdomain}) created {org.created_at:%Y-%m-%d}")
            if args.yes:
                delete_organization(db, org.id)
                db.commit()
                delete_org_files(str(org.id))
        print(f"{len(doomed)} unverified organization(s) {'deleted' if args.yes else 'found (dry run, nothing deleted)'}.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
