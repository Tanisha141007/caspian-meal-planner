from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_current_user_id, get_db, get_owned_household
from app.api.schemas import HouseholdCreate, HouseholdUpdate
from app.api.serializers import serialize_household
from app.models import Household

router = APIRouter(prefix="/api/households", tags=["households"])


@router.get("/me")
def get_my_household(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """404 here (not an error state in practice) means "not onboarded yet" -
    the frontend shows the Preferences tab as an onboarding form in that case."""
    household = db.query(Household).filter(Household.owner_user_id == user["id"]).first()
    if household is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No household yet")

    # Backfill for households created before owner_email existed - without an
    # address the Monday email job silently skips them, and the only place the
    # address is available is an authenticated request like this one.
    if not household.owner_email and user["email"]:
        household.owner_email = user["email"]
        db.commit()
    return serialize_household(household)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_household(
    body: HouseholdCreate, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    existing = db.query(Household).filter(Household.owner_user_id == user["id"]).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Household already exists - use PATCH to update it")

    fields = body.model_dump()
    # The weekly chart goes to the address they signed up with unless they
    # explicitly passed another one; PATCH owner_email to change it later.
    fields["owner_email"] = fields.get("owner_email") or user["email"] or None

    household = Household(owner_user_id=user["id"], **fields)
    db.add(household)
    db.commit()
    return serialize_household(household)


@router.get("/{household_id}")
def get_household(household: Household = Depends(get_owned_household)):
    return serialize_household(household)


@router.patch("/{household_id}")
def update_household(body: HouseholdUpdate, household: Household = Depends(get_owned_household), db: Session = Depends(get_db)):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(household, field, value)
    db.commit()
    return serialize_household(household)
