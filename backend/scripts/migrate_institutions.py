"""Explicit, additive upgrade. Never run automatically during application startup.

Run from backend/. The default is a read-only preview. Back up the database first.
No accounts, course IDs, passwords, enrollments or academic records are replaced.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import inspect, text
from app.database import engine
from app.models.institution import Institution, Department


def scope_course_codes(connection):
    """Preserve course IDs while allowing each institution to use its own codes."""
    inspector = inspect(connection)
    old_constraints = [c for c in inspector.get_unique_constraints("courses") if c["column_names"] == ["code"]]
    if old_constraints and connection.dialect.name == "sqlite":
        if connection.execute(text("PRAGMA foreign_keys")).scalar():
            raise ValueError("SQLite migration requires foreign keys disabled before the transaction; use the CLI.")
        expected = {"id", "institution_id", "name", "code", "department", "semester", "course_type", "program",
                    "batch", "semester_number", "section", "enrollment_mode", "credits", "faculty_id", "created_at"}
        if {c["name"] for c in inspector.get_columns("courses")} != expected:
            raise ValueError("Unexpected course columns. Review the migration instead of losing custom data.")
        if any(index["name"] not in {"ix_courses_id", "ix_courses_institution_id"} for index in inspector.get_indexes("courses")):
            raise ValueError("Custom course indexes need a manual migration review")
        if connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='courses'")).first():
            raise ValueError("Custom course triggers need a manual migration review")
        connection.execute(text("""CREATE TABLE courses_institution_upgrade (
            id INTEGER NOT NULL PRIMARY KEY, institution_id INTEGER REFERENCES institutions(id),
            name VARCHAR NOT NULL, code VARCHAR NOT NULL, department VARCHAR, semester VARCHAR,
            course_type VARCHAR NOT NULL DEFAULT 'academic', program VARCHAR, batch VARCHAR,
            semester_number INTEGER, section VARCHAR, enrollment_mode VARCHAR NOT NULL DEFAULT 'elective',
            credits FLOAT, faculty_id INTEGER REFERENCES users(id), created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_courses_institution_code UNIQUE (institution_id, code))"""))
        connection.execute(text("""INSERT INTO courses_institution_upgrade
            (id, institution_id, name, code, department, semester, course_type, program, batch,
             semester_number, section, enrollment_mode, credits, faculty_id, created_at)
            SELECT id, institution_id, name, code, department, semester, course_type, program, batch,
                   semester_number, section, enrollment_mode, credits, faculty_id, created_at FROM courses"""))
        connection.execute(text("DROP TABLE courses"))
        connection.execute(text("ALTER TABLE courses_institution_upgrade RENAME TO courses"))
        connection.execute(text("CREATE INDEX ix_courses_id ON courses(id)"))
        connection.execute(text("CREATE INDEX ix_courses_institution_id ON courses(institution_id)"))
        if connection.execute(text("PRAGMA foreign_key_check")).first():
            raise ValueError("Foreign key validation failed; restore/review the database backup")
    elif old_constraints and connection.dialect.name == "postgresql":
        quote = connection.dialect.identifier_preparer.quote
        for constraint in old_constraints:
            connection.execute(text(f"ALTER TABLE courses DROP CONSTRAINT {quote(constraint['name'])}"))
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_courses_institution_code_idx ON courses(institution_id, code)"))


def migrate(connection, name, domain, email=None):
    inspector = inspect(connection)
    tables = inspector.get_table_names()
    if "users" not in tables or "courses" not in tables:
        raise ValueError("No existing LMS users/courses tables. Start a fresh database with the application instead.")
    # Refuse to absorb orphan records into an already multi-institution deployment.
    if "institutions" in tables:
        domains = connection.execute(text("SELECT email_domain FROM institutions")).scalars().all()
        if domains and domains != [domain]:
            raise ValueError("Other institutions already exist. Legacy ownership needs a manual migration review.")
    Institution.__table__.create(connection, checkfirst=True)
    Department.__table__.create(connection, checkfirst=True)
    for table in ("users", "courses"):
        if "institution_id" not in {c["name"] for c in inspect(connection).get_columns(table)}:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN institution_id INTEGER REFERENCES institutions(id)"))
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_institution_id ON {table} (institution_id)"))
    additions = {
        "users": {"program": "VARCHAR", "batch": "VARCHAR", "semester_number": "INTEGER", "section": "VARCHAR",
                  "institutional_id": "VARCHAR(120)",
                  "must_change_password": "BOOLEAN NOT NULL DEFAULT FALSE",
                  "erp_password_initialized": "BOOLEAN NOT NULL DEFAULT FALSE",
                  "session_version": "INTEGER NOT NULL DEFAULT 0"},
        "courses": {"course_type": "VARCHAR NOT NULL DEFAULT 'academic'", "program": "VARCHAR", "batch": "VARCHAR",
                    "semester_number": "INTEGER", "section": "VARCHAR",
                    "enrollment_mode": "VARCHAR NOT NULL DEFAULT 'elective'", "credits": "FLOAT"},
    }
    for table, columns in additions.items():
        present = {c["name"] for c in inspect(connection).get_columns(table)}
        for column, definition in columns.items():
            if column not in present:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
    institution_id = connection.execute(text("SELECT id FROM institutions WHERE email_domain = :domain"), {"domain": domain}).scalar()
    if institution_id is None:
        result = connection.execute(Institution.__table__.insert().values(name=name, email=email, email_domain=domain))
        institution_id = result.inserted_primary_key[0]
    for table in ("users", "courses"):
        connection.execute(text(f"UPDATE {table} SET institution_id = :id WHERE institution_id IS NULL"), {"id": institution_id})
    names = connection.execute(text("SELECT department FROM users WHERE institution_id=:id UNION SELECT department FROM courses WHERE institution_id=:id"), {"id": institution_id}).scalars().all()
    canonical = {}
    for value in sorted(x for x in names if x and x.strip()):
        canonical.setdefault(value.strip().lower(), value.strip())
    for key, value in canonical.items():
        existing = connection.execute(text("SELECT name FROM departments WHERE institution_id=:id AND lower(name)=:key"), {"id": institution_id, "key": key}).scalar()
        if not existing:
            connection.execute(Department.__table__.insert().values(institution_id=institution_id, name=value))
        else:
            value = existing
        for table in ("users", "courses"):
            connection.execute(text(f"UPDATE {table} SET department=:name WHERE institution_id=:id AND lower(trim(department))=:key"), {"name": value, "id": institution_id, "key": key})
    scope_course_codes(connection)
    return institution_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--email", help="Optional real institutional contact email; never invent one")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-confirmed", action="store_true")
    args = parser.parse_args()
    from email_validator import validate_email
    domain = args.domain.strip().lower().lstrip("@")
    # Validate the domain syntactically without claiming a real mailbox exists.
    validate_email(f"domain-check@{domain}", check_deliverability=False)
    email = validate_email(args.email, check_deliverability=False).normalized.lower() if args.email else None
    if email and email.split("@")[-1] != domain:
        parser.error("Contact email must use the institution domain")
    if not 2 <= len(args.name.strip()) <= 160:
        parser.error("Institution name must be 2–160 characters")
    if args.apply and not args.backup_confirmed:
        parser.error("Back up this database, then supply --backup-confirmed")
    with engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        for table in ("users", "courses"):
            if table not in tables:
                parser.error("No existing LMS database found. Check the backend working directory and database configuration.")
        print("Database type:", engine.dialect.name)
        print("Destination institution:", args.name.strip(), "Domain:", domain)
        for table in ("users", "courses"):
            count = connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"{table}: {count} existing records")
    if not args.apply:
        print("Preview only. No database changes were made.")
        return
    # A single transaction on PostgreSQL; take a backup for SQLite DDL safety too.
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.commit()
            # Force an explicit transaction, including SQLite schema changes.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        if engine.dialect.name == "postgresql":
            connection.execute(text("LOCK TABLE users, courses IN SHARE ROW EXCLUSIVE MODE"))
        institution_id = migrate(connection, args.name.strip(), domain, email)
        connection.commit()
    print(f"Migration complete. Institution ID: {institution_id}. Existing records preserved.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Database exceptions may include secrets: do not print the raw exception.
        print("Migration failed. Stop deployment and review the database configuration, backup and ownership. No automatic retry was attempted.")
        sys.exit(1)
