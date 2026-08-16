from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_owned_household
from app.api.schemas import HouseholdCreate, HouseholdUpdate
from app.api.serializers import serialize_household
from app.models import Household

router = APIRouter(prefix="/api/households", tags=["households"])


def _sync_owner_email(household: Household, email: str | None, db: Session):
    if email and household.owner_email != email:
        household.owner_email = email
        db.commit()


@router.get("/me")
def get_my_household(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """404 here (not an error state in practice) means "not onboarded yet" -
    the frontend shows the Preferences tab as an onboarding form in that case."""
    user_id = user["id"]
    household = db.query(Household).filter(Household.owner_user_id == user_id).first()
    if household is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No household yet")
    _sync_owner_email(household, user.get("email"), db)
    return serialize_household(household)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_household(
    body: HouseholdCreate, db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    user_id = user["id"]
    existing = db.query(Household).filter(Household.owner_user_id == user_id).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Household already exists - use PATCH to update it")

    household = Household(owner_user_id=user_id, owner_email=user.get("email"), **body.model_dump())
    db.add(household)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Household already exists - use PATCH to update it")
    return serialize_household(household)


@router.get("/{household_id}")
def get_household(household: Household = Depends(get_owned_household)):
    return serialize_household(household)


@router.patch("/{household_id}")
def update_household(
    body: HouseholdUpdate,
    household: Household = Depends(get_owned_household),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(household, field, value)
    if user.get("email"):
        household.owner_email = user["email"]
    db.commit()
    return serialize_household(household)
