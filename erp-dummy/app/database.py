import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool

from app.config import settings

database_url = settings.database_url
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
if os.getenv("VERCEL") and not database_url.startswith("postgresql+psycopg://"):
    raise RuntimeError("A hosted PostgreSQL DATABASE_URL is required on Vercel")

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {"connect_timeout": 10}
pool_options = {"poolclass": NullPool} if database_url.startswith("postgresql") else {}
engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True, **pool_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_schema_compatibility():
    """Preserve existing ERP student rows while adding role-based identities."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if "erp_students" in tables and "role" not in {column["name"] for column in inspector.get_columns("erp_students")}:
        with engine.begin() as connection:
            qualifier = " IF NOT EXISTS" if engine.dialect.name == "postgresql" else ""
            connection.execute(text(
                f"ALTER TABLE erp_students ADD COLUMN{qualifier} role VARCHAR(20) NOT NULL DEFAULT 'student'"
            ))
    if "erp_courses" in tables and "credits" not in {column["name"] for column in inspector.get_columns("erp_courses")}:
        with engine.begin() as connection:
            qualifier = " IF NOT EXISTS" if engine.dialect.name == "postgresql" else ""
            connection.execute(text(f"ALTER TABLE erp_courses ADD COLUMN{qualifier} credits FLOAT"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
