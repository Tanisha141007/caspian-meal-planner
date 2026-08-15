from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_owned_household
from app.api.schemas import AskAIRequest
from app.config import llm_configured
from app.meal_planner.generator import ask_ai
from app.models import Household

router = APIRouter(prefix="/api/households/{household_id}/ask-ai", tags=["ask-ai"])


@router.post("")
def ask(body: AskAIRequest, household: Household = Depends(get_owned_household)):
    if not llm_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "No LLM provider key configured yet (GEMINI_API_KEY/ANTHROPIC_API_KEY) - can't parse this request",
        )
    try:
        return ask_ai(household.id, body.message)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Ask AI failed: {e}") from e
