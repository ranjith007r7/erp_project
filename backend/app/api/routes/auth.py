"""
Two endpoints that exist before anything else in the system can work:
- POST /api/auth/signup   -> creates a brand-new organization + its first admin user
- POST /api/auth/login    -> checks email+password, hands back a JWT wristband
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.organization import Organization
from app.models.role import Role, Permission
from app.models.user import User
from app.schemas.auth import OrganizationSignup, LoginRequest, TokenResponse, UserOut
from app.api.deps import get_current_user
from app.services.accounting import seed_default_accounts

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: OrganizationSignup, db: Session = Depends(get_db)):
    # Subdomain must be unique across ALL organizations - it's how we'll
    # eventually route "clientname.yourapp.com" to the right tenant.
    existing_org = db.query(Organization).filter(Organization.subdomain == payload.subdomain).first()
    if existing_org:
        raise HTTPException(status_code=400, detail="That subdomain is already taken.")

    existing_user = db.query(User).filter(User.email == payload.admin_email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="That email is already registered.")

    # 1. Create the organization (the tenant).
    org = Organization(name=payload.org_name, subdomain=payload.subdomain)
    db.add(org)
    db.flush()  # lets us use org.id below without a full commit yet

    # 2. Create a default "Admin" role for this org, with full access.
    admin_role = Role(org_id=org.id, name="Admin")
    db.add(admin_role)
    db.flush()

    # Full-access permission per module we currently have. As new modules
    # are added later, add their names to this list so a fresh org's Admin
    # role automatically has access to everything from day one.
    modules = ["core", "dashboard", "crm", "sales", "procurement", "inventory",
               "finance", "hr", "projects", "documents", "reports", "custom_fields"]
    for module in modules:
        for action in ["view", "create", "edit", "delete", "approve"]:
            db.add(Permission(role_id=admin_role.id, module=module, action=action))

    # 3. Create the first user, as that org's Admin.
    admin_user = User(
        org_id=org.id,
        name=payload.admin_name,
        email=payload.admin_email,
        password_hash=hash_password(payload.admin_password),
        role_id=admin_role.id,
    )
    db.add(admin_user)

    # 4. Seed a minimal default Chart of Accounts, so Finance isn't empty
    #    the moment this organization exists - see app/services/accounting.py
    seed_default_accounts(db, org.id)

    db.commit()
    db.refresh(admin_user)

    token = create_access_token({
        "sub": str(admin_user.id),
        "org_id": str(org.id),
        "role": "Admin",
    })
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    # Deliberately vague error message - never reveal whether the email
    # or the password was the wrong part, that helps attackers guess.
    invalid_error = HTTPException(status_code=401, detail="Incorrect email or password.")

    if not user or not verify_password(payload.password, user.password_hash):
        raise invalid_error

    if user.status != "active":
        raise HTTPException(status_code=403, detail="This account has been disabled.")

    role_name = user.role.name if user.role else None
    token = create_access_token({
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": role_name,
    })
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return UserOut(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        org_id=str(current_user.org_id),
        status=current_user.status,
    )
