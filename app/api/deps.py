"""Shared FastAPI dependencies: a request-scoped DB session, and Supabase
JWT verification -> the owning user's id that every app/api/ route scopes
household access by.

Verifies against Supabase's JWKS endpoint (asymmetric ES256/RS256), not a
shared HS256 secret - Supabase's own docs now actively discourage the
shared-secret approach ("almost no benefit... can expose your project's
data to significant security vulnerabilities"), and newer projects may not
even expose one in the classic form. See
https://supabase.com/docs/guides/auth/jwts."""

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException, status
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import SUPABASE_URL
from app.db import get_session
from app.models import Household

_jwks_client = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        # cache_keys=True: caches fetched signing keys, only refetches the
        # JWKS document when it sees a `kid` it doesn't recognize yet (e.g.
        # after Supabase rotates keys) - not on every request.
        _jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True)
    return _jwks_client


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user(authorization: str = Header(default="")) -> dict:
    """Verifies the Supabase-issued JWT against the project's public JWKS and
    returns {"id": sub, "email": email}. 401s on anything wrong - missing
    header, bad signature, expired token - never falls back to an
    unauthenticated mode. 503s instead if auth isn't configured yet at all, so
    that's distinguishable from "your token is bad" during setup.

    The email claim is what Household.owner_email is seeded from: the weekly
    email job runs on a cron with no request and no token, so the address has
    to be persisted at signup rather than read per-request."""
    if not SUPABASE_URL:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Auth isn't configured yet (SUPABASE_URL unset)")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = pyjwt.decode(token, signing_key.key, algorithms=["ES256", "RS256"], audience="authenticated")
    except pyjwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub claim")
    return {"id": user_id, "email": payload.get("email") or ""}


def get_current_user_id(user: dict = Depends(get_current_user)) -> str:
    """The user id alone, for the routes that don't care about the email."""
    return user["id"]


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
