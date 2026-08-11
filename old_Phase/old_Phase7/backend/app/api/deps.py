"""
'Dependencies' are things FastAPI runs automatically before your endpoint
code, and hands you the result. Every protected endpoint in every future
module will use get_current_user the same way — this is the ONE place
that checks "is this request's login token valid?" for the whole app.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

# This tells FastAPI's auto-generated /docs page where to send a login
# request from the "Authorize" button — it doesn't do any work itself.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_error

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_error

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or user.status != "active":
        raise credentials_error

    return user


def get_org_id(current_user: User = Depends(get_current_user)) -> str:
    """
    Every CRM/Sales/etc. route needs to filter its queries down to the
    logged-in user's own organization - never showing one client's data
    to another. Rather than repeat `str(current_user.org_id)` in every
    single route, every module imports this one helper instead.
    """
    return str(current_user.org_id)
