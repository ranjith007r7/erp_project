from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.services.search import global_search, RESULTS_PER_TYPE

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(get_current_user)])


FULL_RESULTS_PER_TYPE = 50


@router.get("")
def search(q: str, full: bool = False, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    """
    `full=true` is what the dedicated /search results page uses - a much
    higher per-type cap than the header dropdown's quick-glance 5, since
    someone landing on a real results page wants to actually see
    everything reasonably matching, not just a preview.
    """
    if not q or len(q.strip()) < 2:
        return {"query": q, "results": []}
    limit = FULL_RESULTS_PER_TYPE if full else RESULTS_PER_TYPE
    results = global_search(db, org_id, current_user.role_id, q.strip(), limit_per_type=limit)
    return {"query": q, "results": results}
