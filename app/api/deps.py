"""Shared FastAPI dependencies: a request-scoped DB session, and Supabase
JWT verification -> the owning user's id that every app/api/ route scopes
household access by.

Verifies against Supabase's JWKS endpoint (asymmetric ES256/RS256), not a
shared HS256 secret - Supabase's own docs now actively discourage the
shared-secret approach ("almost no benefit... can expose your project's
data to significant security vulnerabilities"), and newer projects may not
even expose one in the classic form. See
https://supabase.com/docs/guides/auth/jwts."""

import ssl

import certifi
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
        # Explicit certifi CA bundle rather than relying on the host
        # Python's default trust store - hit this live: a python.org-
        # installed Python on macOS has no system CA store wired up by
        # default, so the JWKS fetch failed with CERTIFICATE_VERIFY_FAILED
        # until this was explicit. Harmless/redundant on hosts that already
        # have a working default (most Linux deploys), so safe everywhere.
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        # cache_keys=True: caches fetched signing keys, only refetches the
        # JWKS document when it sees a `kid` it doesn't recognize yet (e.g.
        # after Supabase rotates keys) - not on every request.
        _jwks_client = PyJWKClient(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json", cache_keys=True, ssl_context=ssl_context
        )
    return _jwks_client


def get_db():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_current_user(authorization: str = Header(default="")) -> dict:
    """Verifies the Supabase-issued JWT against the project's public JWKS
    and returns the user claims we store against households. 401s on anything wrong - missing header,
    bad signature, expired token - never falls back to an unauthenticated
    mode. 503s instead if auth isn't configured yet at all, so that's
    distinguishable from "your token is bad" during setup."""
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
    return {"id": user_id, "email": payload.get("email")}


def get_current_user_id(user: dict = Depends(get_current_user)) -> str:
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
