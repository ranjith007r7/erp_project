from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import auth, crm, sales, finance, inventory, procurement, hr, projects, dashboard

# Importing app.models here (even though unused directly) registers every
# table with Base.metadata - needed so Alembic's autogenerate can see
# every model when comparing against the real database schema.
import app.models  # noqa: F401

app = FastAPI(
    title="Base ERP API",
    description="Core/Platform + CRM + Sales + Finance + Inventory + Procurement + HR + Projects - Phase 6",
    version="0.6.0",
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
def health_check():
    """Used by hosting providers to check the service is alive."""
    return {"status": "ok"}
