"""Shared FastAPI dependencies: a request-scoped DB session, and Supabase
JWT verification -> the owning user's id that every app/api/ route scopes
household access by."""

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import SUPABASE_JWT_SECRET
from app.db import get_session
from app.models import Household


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user_id(authorization: str = Header(default="")) -> str:
    """Verifies the Supabase-issued JWT's signature (the project's JWT
    secret - Supabase dashboard: Settings -> API) and returns its `sub`
    claim. 401s on anything wrong - missing header, bad signature, expired
    token - never falls back to an unauthenticated mode. 503s instead if
    auth isn't configured yet at all, so that's distinguishable from "your
    token is bad" during setup."""
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Auth isn't configured yet (SUPABASE_JWT_SECRET unset)"
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = pyjwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
    except pyjwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub claim")
    return user_id


def get_owned_household(
    household_id: int,
    db: Session = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> Household:
    """Every app/api/ route that operates on one household depends on this
    instead of loading it directly - 404s (not 403) for a household that
    doesn't exist OR belongs to someone else, so a guess-the-id probe can't
    distinguish the two."""
    household = db.get(Household, household_id)
    if household is None or household.owner_user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Household not found")
    return household
