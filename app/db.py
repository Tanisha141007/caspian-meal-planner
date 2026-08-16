from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL

# check_same_thread only means anything to SQLite; Postgres (psycopg2) errors
# if you pass it. Keeps local dev on SQLite and prod on Postgres (Supabase)
# working off the same DATABASE_URL env var with no code change.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def init_db():
    """Brings the DB to the latest migration - always through Alembic, never
    a raw create_all(). This used to be create_all() directly ("quick-start
    for scripts/tests, real changes go through Alembic separately"), which
    sounds harmless but isn't: any script that called this on a *fresh* DB
    file created the tables correctly but left alembic_version unstamped,
    so a later `alembic upgrade head` (e.g. after a schema change) would
    then fail with "table already exists" - hit this live. Alembic's
    upgrade is idempotent (a no-op on an already-current DB), so routing
    everything through it here removes the footgun with no downside."""
    from app import models  # noqa: F401 (registers models on Base, needed by migrations/env.py)
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_INI.parent / "migrations"))
    command.upgrade(cfg, "head")


def get_session():
    return SessionLocal()
