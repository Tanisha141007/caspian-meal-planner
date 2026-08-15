"""The real JSON API mealtime-harmony talks to. Separate FastAPI app from
app/web/main.py's Jinja demo (that one stays as a local-only preview) -
this is what M5 deploys to Railway.

Run with: uvicorn app.api.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import ask_ai, households, notify, plan, recipes
from app.config import CORS_ORIGINS
from app.db import init_db

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
app.include_router(recipes.router)
app.include_router(plan.router)
app.include_router(ask_ai.router)
app.include_router(notify.router)


@app.get("/health")
def health():
    return {"status": "ok"}
