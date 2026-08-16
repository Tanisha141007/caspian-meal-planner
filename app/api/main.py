"""The real JSON API mealtime-harmony talks to. Separate FastAPI app from
app/web/main.py's Jinja demo (that one stays as a local-only preview) -
this is what M5 deploys to Render.

Run with: uvicorn app.api.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import ask_ai, auth, households, internal, notify, plan, recipes
from app.config import CASPIAN_API_KEY, CORS_ORIGINS
from app.db import init_db

logger = logging.getLogger("api")

init_db()

app = FastAPI(title="Caspian Meal Planner API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(households.router)
app.include_router(auth.router)
app.include_router(recipes.router)
app.include_router(plan.router)
app.include_router(ask_ai.router)
app.include_router(notify.router)
app.include_router(internal.router)


@app.on_event("startup")
def _connect_caspian():
    """Registers the on_message handler once per process so a message
    dispatched by /internal/poll-messages (or a send from /notify-cook) has
    somewhere to go, and so the very first request doesn't pay the connect
    cost. Only if CASPIAN_API_KEY is set, so a deploy that hasn't
    configured it yet still boots and serves everything else instead of
    crashing on startup."""
    if not CASPIAN_API_KEY:
        logger.warning("CASPIAN_API_KEY not set - messaging routes will 503 until it's configured")
        return
    from app.messaging.handler import ensure_ready

    try:
        ensure_ready()
    except Exception:
        logger.exception("Failed to connect Caspian channel on startup - will retry on first use")


@app.get("/health")
def health():
    return {"status": "ok"}
