from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id
from app.services.search import global_search

router = APIRouter(prefix="/api/search", tags=["search"], dependencies=[Depends(get_current_user)])


@router.get("")
def search(q: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id), current_user=Depends(get_current_user)):
    if not q or len(q.strip()) < 2:
        return {"query": q, "results": []}
    results = global_search(db, org_id, current_user.role_id, q.strip())
    return {"query": q, "results": results}
