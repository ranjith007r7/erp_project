"""
Sets up the connection to PostgreSQL and gives the rest of the app a clean
way to borrow a database "session" (think of it as a temporary, safe
conversation with the database that closes itself when done).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Every model (table) in the app inherits from this Base.
Base = declarative_base()


def get_db():
    """
    FastAPI calls this before running any endpoint that needs the database.
    It hands over one session, then guarantees it gets closed afterwards —
    even if the endpoint crashes halfway through.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
