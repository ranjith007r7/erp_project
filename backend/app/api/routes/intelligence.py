"""
Unified Intelligence Layer API: plain-English questions over the caller's own
organization's data.

Access (two ticks on the existing `intelligence` row of the permissions grid):

  view     use Ask Data on the modules the role can ALREADY open. A role with
           inventory.view can ask about stock; it cannot ask about HR or invoices.
  approve  ALSO ask about restricted data (salary, payroll). Additional, never a
           substitute: it needs HR module access too.

Admin gets everything. The rules are in services/intelligence/access.py and are
enforced in the prompt, the SQL validator and the database itself.

Every question is written to the audit log (who asked what, and how it
ended), including ones that were refused or blocked, because a feature that
can read salaries should be able to answer "who asked?".
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_org_id, require_permission
from app.core.config import settings
from app.core.database import get_db
from app.schemas.intelligence import AccessInfo, AskRequest, AskResponse, StatusResponse
from app.services.audit import log_audit_event
from app.services.intelligence.executor import UilNotConfigured, ensure_configured
from app.services.intelligence.llm import LLMNotConfigured, get_llm_client
from app.services.intelligence.access import resolve_access
from app.services.intelligence.manifest import MODULE_LABELS, VIEWS, example_questions, view_summary
from app.services.intelligence.pipeline import answer_question

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"], dependencies=[Depends(get_current_user)])


def get_llm():
    """A dependency (not a direct call) so tests can substitute a scripted model."""
    try:
        return get_llm_client()
    except LLMNotConfigured as exc:
        raise HTTPException(503, str(exc))


@router.get("/status", response_model=StatusResponse, dependencies=[Depends(require_permission("intelligence", "view"))])
def status(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    access = resolve_access(db, current_user)
    return StatusResponse(
        llm_configured=bool(settings.GEMINI_API_KEY),
        database_configured=bool(settings.UIL_DATABASE_URL),
        rows_sent_to_llm=settings.UIL_SEND_ROWS_TO_LLM,
        model=settings.GEMINI_MODEL,
        access=AccessInfo(
            is_admin=access.is_admin,
            restricted=access.restricted,
            modules=sorted(MODULE_LABELS.get(m, m) for m in access.modules),
        ),
    )


@router.get("/manifest", dependencies=[Depends(require_permission("intelligence", "view"))])
def manifest(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """Only what THIS user may ask about, plus a plain list of what is locked and why."""
    access = resolve_access(db, current_user)
    allowed = access.allowed_names()
    locked = [
        {"name": v.name, "description": v.description, "needs": access.missing_for(v)}
        for v in VIEWS if v.name not in allowed
    ]
    return {"views": view_summary(allowed), "locked": locked, "examples": example_questions(allowed)}


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(require_permission("intelligence", "view"))])
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
    current_user=Depends(get_current_user),
    llm=Depends(get_llm),
):
    try:
        ensure_configured()  # check before spending any of the free LLM quota
    except UilNotConfigured as exc:
        raise HTTPException(503, str(exc))

    access = resolve_access(db, current_user)  # resolved fresh on EVERY question: a revoked tick applies immediately
    result = answer_question(db, org_id, payload.question, [h.model_dump() for h in payload.history], llm, access)

    log_audit_event(db, org_id, current_user.id, f"intelligence_query [{result.stage}]: {payload.question[:200]}", "Intelligence")
    db.commit()
    return result.to_dict()
