from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.api.routes import auth

# Importing app.models here (even though unused directly) registers every
# table with Base.metadata - see the comment in app/models/__init__.py
import app.models  # noqa: F401

app = FastAPI(
    title="Base ERP API",
    description="Core/Platform layer - Organizations, Users, Roles, Permissions, Audit Log, Notifications, Custom Fields",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)


@app.on_event("startup")
def on_startup():
    """
    Creates every table that doesn't exist yet, based on the models we've
    imported above. This is fine while we're actively building (Phase 1).
    Once the schema stabilizes, we'll switch to Alembic migrations instead,
    so that changes to production data are tracked and reversible.
    """
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "Base ERP API is running", "docs": "/docs"}


@app.get("/health")
def health_check():
    """Used by hosting providers to check the service is alive."""
    return {"status": "ok"}
