"""
Reports & Analytics routes. Deliberately last of the 10 modules to be
built (per the build order in the Strategy Guide) since it only READS
data every other module already produced - nothing here writes to any
other module's tables.

Two kinds of endpoint:
1. Six `/summary` endpoints (one per module area) - live-computed numbers,
   never stored, via app/services/reports.py.
2. Saved Reports CRUD - lets a user save which report + which filters
   they were looking at, so they can reopen the same VIEW later. Only the
   config is saved, never the numbers themselves, so a saved report is
   always showing today's real data when reopened, not a stale snapshot.
Plus one CSV export endpoint that flattens any of the six summaries into
a downloadable file, since a real client demo will expect to be able to
export a report, not just look at it on screen.
"""
import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.reports import SavedReport
from app.schemas.reports import SavedReportCreate, SavedReportOut
from app.services import reports as report_service

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


@router.get("/sales-summary", dependencies=[Depends(require_permission("reports", "view"))])
def sales_summary(months: int = 6, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.sales_summary(db, org_id, months=months)


@router.get("/finance-summary", dependencies=[Depends(require_permission("reports", "view"))])
def finance_summary(months: int = 6, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.finance_summary(db, org_id, months=months)


@router.get("/inventory-summary", dependencies=[Depends(require_permission("reports", "view"))])
def inventory_summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.inventory_summary(db, org_id)


@router.get("/procurement-summary", dependencies=[Depends(require_permission("reports", "view"))])
def procurement_summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.procurement_summary(db, org_id)


@router.get("/hr-summary", dependencies=[Depends(require_permission("reports", "view"))])
def hr_summary(months: int = 6, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.hr_summary(db, org_id, months=months)


@router.get("/crm-funnel", dependencies=[Depends(require_permission("reports", "view"))])
def crm_funnel(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.crm_funnel(db, org_id)


@router.get("/projects-summary", dependencies=[Depends(require_permission("reports", "view"))])
def projects_summary(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return report_service.projects_summary(db, org_id)


@router.get("/saved", response_model=list[SavedReportOut], dependencies=[Depends(require_permission("reports", "view"))])
def list_saved_reports(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return (
        db.query(SavedReport)
        .filter(SavedReport.org_id == org_id)
        .order_by(SavedReport.created_at.desc())
        .all()
    )


@router.post("/saved", response_model=SavedReportOut, status_code=201, dependencies=[Depends(require_permission("reports", "create"))])
def create_saved_report(
    payload: SavedReportCreate,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    current_user=Depends(get_current_user),
):
    if payload.module not in report_service.REPORT_FUNCTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown report module '{payload.module}'")

    saved = SavedReport(
        org_id=org_id,
        name=payload.name,
        module=payload.module,
        query_config=payload.query_config,
        created_by=current_user.id,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


@router.delete("/saved/{report_id}", status_code=204, dependencies=[Depends(require_permission("reports", "delete"))])
def delete_saved_report(report_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    saved = db.query(SavedReport).filter(SavedReport.id == report_id, SavedReport.org_id == org_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail="Saved report not found")
    db.delete(saved)
    db.commit()
    return None


def _flatten_for_csv(data: dict) -> list[dict]:
    """
    Report summaries are nested JSON (lists inside dicts, dicts inside
    dicts) - a CSV needs flat rows. Rather than write a bespoke flattener
    per report type, this walks the structure generically: any list of
    dicts becomes its own block of rows, any flat key/value becomes a
    one-row block. Good enough for a demo export; a hand-tuned per-report
    CSV layout is a reasonable Phase 10 polish item, not a blocker now.
    """
    rows: list[dict] = []
    scalars: dict = {}
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            rows.append({"section": key})
            for item in value:
                rows.append(item)
        elif isinstance(value, dict):
            rows.append({"section": key})
            for sub_key, sub_value in value.items():
                rows.append({sub_key: sub_value})
        else:
            scalars[key] = value
    if scalars:
        rows.insert(0, scalars)
    return rows


@router.get("/export/{report_type}", dependencies=[Depends(require_permission("reports", "view"))])
def export_report_csv(report_type: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    fn = report_service.REPORT_FUNCTIONS.get(report_type)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown report type '{report_type}'")

    data = fn(db, org_id)
    rows = _flatten_for_csv(data)

    buffer = io.StringIO()
    fieldnames: list[str] = []
    for row in rows:
        for k in row.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, restval="")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={report_type}_report.csv"},
    )
