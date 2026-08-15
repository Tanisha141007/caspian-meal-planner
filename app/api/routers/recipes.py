from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_owned_household
from app.api.serializers import CATEGORY_FRONTEND_TO_BACKEND, SEASON_FRONTEND_TO_BACKEND, serialize_recipe
from app.meal_planner.generator import candidate_recipes
from app.models import Household

router = APIRouter(prefix="/api/households/{household_id}/recipes", tags=["recipes"])


@router.get("")
def list_recipes(
    slot: str | None = None,
    season: str | None = None,
    category: str | None = None,
    cuisine_style: str | None = None,
    max_minutes: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    household: Household = Depends(get_owned_household),
):
    """Powers Discover's rows. Always starts from the household's own
    diet/allergy-safe candidate set (candidate_recipes(), same function the
    weekly generator uses) rather than the raw recipe table - "discover"
    shouldn't surface anything the household couldn't actually eat."""
    results = candidate_recipes(db, household)

    if slot:
        results = [r for r in results if slot in (r.meal_types or [])]
    if season:
        backend_season = SEASON_FRONTEND_TO_BACKEND.get(season, season)
        results = [r for r in results if backend_season in (r.season_tags or []) or "all-season" in (r.season_tags or [])]
    if category:
        backend_category = CATEGORY_FRONTEND_TO_BACKEND.get(category, category)
        results = [r for r in results if r.main_ingredient_category == backend_category]
    if cuisine_style:
        results = [r for r in results if r.cuisine_style == cuisine_style]
    if max_minutes:
        results = [r for r in results if r.prep_time_min <= max_minutes]

    return [serialize_recipe(r) for r in results[:limit]]
