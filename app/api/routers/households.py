from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db, get_owned_household
from app.api.schemas import HouseholdCreate, HouseholdUpdate
from app.api.serializers import serialize_household
from app.models import Household

router = APIRouter(prefix="/api/households", tags=["households"])


@router.get("/me")
def get_my_household(db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)):
    """404 here (not an error state in practice) means "not onboarded yet" -
    the frontend shows the Preferences tab as an onboarding form in that case."""
    household = db.query(Household).filter(Household.owner_user_id == user_id).first()
    if household is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No household yet")
    return serialize_household(household)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_household(
    body: HouseholdCreate, db: Session = Depends(get_db), user_id: str = Depends(get_current_user_id)
):
    existing = db.query(Household).filter(Household.owner_user_id == user_id).first()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Household already exists - use PATCH to update it")

    household = Household(owner_user_id=user_id, **body.model_dump())
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
