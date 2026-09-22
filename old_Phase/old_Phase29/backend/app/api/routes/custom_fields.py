"""
The customization engine, made real. Two endpoint groups:

1. Definitions (/api/custom-fields) — an admin defines what extra fields
   exist for a given entity_type. This is what an org-level Settings
   screen manages.

2. Values (/api/custom-fields/values) — any user reading or saving a real
   record's custom field data. GET returns every active field definition
   for that entity_type MERGED with whatever value already exists for
   that specific entity_id (or null if unset) — this single response is
   everything <CustomFieldsSection> needs to render itself, so the
   frontend never has to make two calls or reconcile two lists itself.

Deliberately module-agnostic: nothing in this file mentions "product" or
"lead" by name. The same code serves every module, which is the entire
point of this phase — a generic mechanism, not per-module logic.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.api.deps import get_current_user, get_org_id, require_permission
from app.models.custom_field import CustomField, CustomFieldValue
from app.schemas.custom_field import (
    CustomFieldCreate, CustomFieldUpdate, CustomFieldOut,
    CustomFieldValuesSetRequest, CustomFieldValueOut,
)

router = APIRouter(prefix="/api/custom-fields", tags=["custom-fields"], dependencies=[Depends(get_current_user)])


# ---------------- Definitions ----------------

@router.post("", response_model=CustomFieldOut, status_code=201, dependencies=[Depends(require_permission("custom_fields", "create"))])
def create_custom_field(payload: CustomFieldCreate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    if payload.field_type == "dropdown" and not payload.options:
        raise HTTPException(400, "dropdown fields require a non-empty options list")

    existing = db.query(CustomField).filter(
        CustomField.org_id == org_id,
        CustomField.entity_type == payload.entity_type,
        CustomField.field_name == payload.field_name,
    ).first()
    if existing:
        raise HTTPException(400, f"A field named '{payload.field_name}' already exists for {payload.entity_type}")

    field = CustomField(org_id=org_id, **payload.model_dump())
    db.add(field)
    db.commit()
    db.refresh(field)
    return field


@router.get("", response_model=list[CustomFieldOut], dependencies=[Depends(require_permission("custom_fields", "view"))])
def list_custom_fields(
    entity_type: str | None = None,
    module: str | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    org_id: str = Depends(get_org_id),
):
    """
    Used two ways: entity_type set = "what fields render on this record's
    form" (the common case, called by <CustomFieldsSection>). No filters
    at all = "list everything" for an admin Settings screen.
    """
    query = db.query(CustomField).filter(CustomField.org_id == org_id)
    if entity_type:
        query = query.filter(CustomField.entity_type == entity_type)
    if module:
        query = query.filter(CustomField.module == module)
    if not include_inactive:
        query = query.filter(CustomField.is_active.is_(True))
    return query.order_by(CustomField.display_order, CustomField.created_at).all()


@router.patch("/{field_id}", response_model=CustomFieldOut, dependencies=[Depends(require_permission("custom_fields", "edit"))])
def update_custom_field(field_id: str, payload: CustomFieldUpdate, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    field = db.query(CustomField).filter(CustomField.id == field_id, CustomField.org_id == org_id).first()
    if not field:
        raise HTTPException(404, "Custom field not found")

    for key, val in payload.model_dump(exclude_unset=True).items():
        setattr(field, key, val)

    db.commit()
    db.refresh(field)
    return field


@router.delete("/{field_id}", status_code=204, dependencies=[Depends(require_permission("custom_fields", "delete"))])
def delete_custom_field(field_id: str, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    A hard delete, not a deactivate — cascades to every stored value via
    the model's cascade="all, delete-orphan". Deliberately different from
    update's is_active toggle: PATCH is_active=false is the safe way to
    retire a field while keeping its historical values; DELETE is for
    "I created this by mistake" and genuinely wants the data gone too.
    """
    field = db.query(CustomField).filter(CustomField.id == field_id, CustomField.org_id == org_id).first()
    if not field:
        raise HTTPException(404, "Custom field not found")
    db.delete(field)
    db.commit()


# ---------------- Values ----------------

@router.get("/values", response_model=list[CustomFieldValueOut], dependencies=[Depends(require_permission("custom_fields", "view"))])
def get_custom_field_values(entity_type: str, entity_id: UUID, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Every active field definition for entity_type, left-joined against
    whatever value this specific entity_id already has. A field with no
    saved value yet still appears, with value=None — the frontend needs
    to know the field EXISTS even before anyone has filled it in.
    """
    fields = db.query(CustomField).filter(
        CustomField.org_id == org_id,
        CustomField.entity_type == entity_type,
        CustomField.is_active.is_(True),
    ).order_by(CustomField.display_order, CustomField.created_at).all()

    existing_values = {
        v.custom_field_id: v.value
        for v in db.query(CustomFieldValue).filter(
            CustomFieldValue.org_id == org_id,
            CustomFieldValue.entity_type == entity_type,
            CustomFieldValue.entity_id == entity_id,
        ).all()
    }

    return [
        CustomFieldValueOut(
            custom_field_id=f.id,
            field_name=f.field_name,
            field_type=f.field_type,
            value=existing_values.get(f.id),
        )
        for f in fields
    ]


@router.post("/values", status_code=200, dependencies=[Depends(require_permission("custom_fields", "edit"))])
def set_custom_field_values(payload: CustomFieldValuesSetRequest, db: Session = Depends(get_db), org_id: str = Depends(get_org_id)):
    """
    Upsert every submitted value in one call. Validates each custom_field_id
    actually belongs to this org and this entity_type before writing —
    without that check, a stale frontend field list could silently write
    a value against the wrong field or another org's field definition.
    """
    valid_field_ids = {
        f.id for f in db.query(CustomField.id).filter(
            CustomField.org_id == org_id,
            CustomField.entity_type == payload.entity_type,
        ).all()
    }

    for item in payload.values:
        if item.custom_field_id not in valid_field_ids:
            raise HTTPException(400, f"custom_field_id {item.custom_field_id} does not belong to {payload.entity_type} for this organization")

        existing = db.query(CustomFieldValue).filter(
            CustomFieldValue.org_id == org_id,
            CustomFieldValue.custom_field_id == item.custom_field_id,
            CustomFieldValue.entity_id == payload.entity_id,
        ).first()

        if existing:
            existing.value = item.value
        else:
            db.add(CustomFieldValue(
                org_id=org_id,
                custom_field_id=item.custom_field_id,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                value=item.value,
            ))

    db.commit()
    return {"status": "saved", "count": len(payload.values)}
