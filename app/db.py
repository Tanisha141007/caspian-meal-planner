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


def init_db():
    """Quick-start schema creation for local dev/tests/scripts (create-if-missing,
    no diffing). Real schema changes go through Alembic (`alembic upgrade head`,
    see migrations/) so they apply safely to a populated Postgres DB too - this
    stays around purely so `scripts/*.py` and tests don't need Alembic wired up
    just to get a working local SQLite file."""
    from app import models  # noqa: F401 (registers models on Base)

    Base.metadata.create_all(engine)


def get_session():
    return SessionLocal()
