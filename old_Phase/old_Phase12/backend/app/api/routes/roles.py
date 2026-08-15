"""
Role/Permission/User management. Gated behind module="core" permissions —
Admin already has full "core" access from signup, so this doesn't need
special-casing; it's just another module in the same system it manages.

No email-invite flow exists (no outbound email anywhere in this codebase
yet — that's Phase 13). Creating a user here sets a real password
directly, same tradeoff signup itself makes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import hash_password
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.role import Role, Permission
from app.models.user import User
from app.schemas.roles import (
    RoleCreate, RoleOut, PermissionCreate, PermissionOut,
    UserCreate, UserRoleUpdate, UserManagementOut,
)

router = APIRouter(prefix="/api/core", tags=["roles-users"], dependencies=[Depends(get_current_user)])


# ---------------- Roles ----------------
@router.post("/roles", response_model=RoleOut, status_code=201, dependencies=[Depends(require_permission("core", "create"))])
def create_role(payload: RoleCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    existing = db.query(Role).filter(Role.org_id == org_id, Role.name == payload.name).first()
    if existing:
        raise HTTPException(400, f"A role named '{payload.name}' already exists.")
    role = Role(org_id=org_id, name=payload.name)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.get("/roles", response_model=list[RoleOut], dependencies=[Depends(require_permission("core", "view"))])
def list_roles(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    return db.query(Role).filter(Role.org_id == org_id).all()


@router.post("/roles/{role_id}/permissions", response_model=PermissionOut, status_code=201, dependencies=[Depends(require_permission("core", "edit"))])
def grant_permission(role_id: str, payload: PermissionCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    role = db.query(Role).filter(Role.id == role_id, Role.org_id == org_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    existing = db.query(Permission).filter(
        Permission.role_id == role_id, Permission.module == payload.module, Permission.action == payload.action
    ).first()
    if existing:
        return existing  # idempotent - granting the same permission twice isn't an error
    perm = Permission(role_id=role_id, module=payload.module, action=payload.action)
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


@router.get("/roles/{role_id}/permissions", response_model=list[PermissionOut], dependencies=[Depends(require_permission("core", "view"))])
def list_role_permissions(role_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    role = db.query(Role).filter(Role.id == role_id, Role.org_id == org_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    return db.query(Permission).filter(Permission.role_id == role_id).all()


@router.delete("/roles/{role_id}/permissions/{permission_id}", status_code=204, dependencies=[Depends(require_permission("core", "delete"))])
def revoke_permission(role_id: str, permission_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    role = db.query(Role).filter(Role.id == role_id, Role.org_id == org_id).first()
    if not role:
        raise HTTPException(404, "Role not found")
    perm = db.query(Permission).filter(Permission.id == permission_id, Permission.role_id == role_id).first()
    if not perm:
        raise HTTPException(404, "Permission not found")
    db.delete(perm)
    db.commit()


# ---------------- Users ----------------
@router.get("/users", response_model=list[UserManagementOut], dependencies=[Depends(require_permission("core", "view"))])
def list_users(db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    users = db.query(User).options(joinedload(User.role)).filter(User.org_id == org_id).all()
    return [
        UserManagementOut(
            id=u.id, name=u.name, email=u.email, role_id=u.role_id,
            role_name=u.role.name if u.role else None, status=u.status, created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users", response_model=UserManagementOut, status_code=201, dependencies=[Depends(require_permission("core", "create"))])
def create_user(payload: UserCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(400, "A user with this email already exists.")

    if payload.role_id:
        role = db.query(Role).filter(Role.id == payload.role_id, Role.org_id == org_id).first()
        if not role:
            raise HTTPException(404, "Role not found in this organization.")

    user = User(
        org_id=org_id,
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role_id=payload.role_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return UserManagementOut(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=user.role.name if user.role else None, status=user.status, created_at=user.created_at,
    )


@router.patch("/users/{user_id}/role", response_model=UserManagementOut, dependencies=[Depends(require_permission("core", "edit"))])
def update_user_role(user_id: str, payload: UserRoleUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    user = db.query(User).filter(User.id == user_id, User.org_id == org_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if payload.role_id:
        role = db.query(Role).filter(Role.id == payload.role_id, Role.org_id == org_id).first()
        if not role:
            raise HTTPException(404, "Role not found in this organization.")
    user.role_id = payload.role_id
    db.commit()
    db.refresh(user)
    return UserManagementOut(
        id=user.id, name=user.name, email=user.email, role_id=user.role_id,
        role_name=user.role.name if user.role else None, status=user.status, created_at=user.created_at,
    )
