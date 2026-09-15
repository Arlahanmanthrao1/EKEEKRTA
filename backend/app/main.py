from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
from app.config import settings

on_vercel = bool(os.getenv("VERCEL"))
if on_vercel and (len(settings.secret_key) < 32 or settings.secret_key.startswith(("change-this", "replace-this"))):
    raise RuntimeError("Set a unique random SECRET_KEY of at least 32 characters before deployment.")
origins = [origin.strip().rstrip("/") for origin in settings.allowed_origins.split(",") if origin.strip()]
if on_vercel and (not origins or any(not origin.startswith("https://") or "*" in origin for origin in origins)):
    raise RuntimeError("Set ALLOWED_ORIGINS to the exact HTTPS frontend URL before deployment.")

from app.database import Base, engine, ensure_schema_compatibility
import app.models  # noqa: F401 - imports every model so Base knows about all tables
from app.routers import auth, users, courses, attendance, assignments, quiz, materials, institutions, calendar, schedule, programming, erp, ai, lectures
from app.core.institution_domains import configured_login_origins

# Existing databases require the reviewed migration before this release can start.
# Never silently invent an institution or recreate populated tables.
from sqlalchemy import inspect
inspector = inspect(engine)
for table in ("users", "courses"):
    if table in inspector.get_table_names() and "institution_id" not in {column["name"] for column in inspector.get_columns(table)}:
        raise RuntimeError("Institution migration required. Back up the database and run scripts/migrate_institutions.py before starting this release.")
Base.metadata.create_all(bind=engine)
ensure_schema_compatibility()

app = FastAPI(title="EKEEKRTA API", version="0.1.0",
              docs_url=None if on_vercel else "/docs", redoc_url=None if on_vercel else "/redoc",
              openapi_url=None if on_vercel else "/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys(origins + configured_login_origins())),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(institutions.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(courses.router)
app.include_router(attendance.router)
app.include_router(assignments.router)
app.include_router(quiz.router)
app.include_router(materials.router)
app.include_router(calendar.router)
app.include_router(schedule.router)
app.include_router(programming.router)
app.include_router(erp.router)
app.include_router(ai.router)
app.include_router(lectures.router)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "lms-backend"}
