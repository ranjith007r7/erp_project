from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.routes import auth, crm, sales, finance, inventory, procurement, hr, projects, documents, dashboard, reports, custom_fields, notifications, roles

# Importing app.models here (even though unused directly) registers every
# table with Base.metadata - needed so Alembic's autogenerate can see
# every model when comparing against the real database schema.
import app.models  # noqa: F401

app = FastAPI(
    title="Base ERP API",
    description="Core/Platform + CRM + Sales + Finance + Inventory + Procurement + HR + Projects + Documents + Reports + Custom Fields + RBAC - Phase 13",
    version="0.13.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(crm.router)
app.include_router(sales.router)
app.include_router(finance.router)
app.include_router(inventory.router)
app.include_router(procurement.router)
app.include_router(hr.router)
app.include_router(projects.router)
app.include_router(documents.router)
app.include_router(reports.router)
app.include_router(custom_fields.router)
app.include_router(notifications.router)
app.include_router(roles.router)
app.include_router(dashboard.router)

# NOTE: there used to be a startup hook here calling
# Base.metadata.create_all(bind=engine) to auto-create tables. That's
# removed now - Alembic owns the schema going forward (see alembic/ and
# MANUAL.md Part 10). The database schema is created/changed ONLY by
# running `alembic upgrade head`, never automatically at app startup.
# This is what makes schema changes trackable, reviewable, and reversible,
# instead of happening silently.


@app.get("/")
def root():
    return {"message": "Base ERP API is running", "docs": "/docs"}


@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """
    Used by hosting providers to check the service is alive - but the
    previous version of this only proved the Python process itself was
    running, not that anything it actually depends on worked. A FastAPI
    process can stay "up" while its database connection is completely
    dead (wrong credentials after a rotation, DB out of connections,
    Supabase paused after 7 days of inactivity - a real, documented
    behavior in this project's own free-tier notes) - and the old
    /health would have kept reporting "ok" the whole time. This runs an
    actual trivial query, so a dead DB shows up here immediately instead
    of only being discovered when a real user's request fails.
    """
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    overall_status = "ok" if db_status == "ok" else "degraded"
    return {"status": overall_status, "database": db_status}
