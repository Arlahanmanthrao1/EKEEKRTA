"""Operator-only backup, restore rehearsal and guarded production migration.

Uses the privately saved .env.production-migration, never prints credentials.
PostgreSQL utilities must be supplied explicitly. Backup directory must be private.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from urllib.parse import urlsplit, unquote, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text


def fingerprint(connection, tables):
    result = {}
    quote = connection.dialect.identifier_preparer.quote
    for table in tables:
        rows = []
        for row in connection.execute(text(f"SELECT * FROM {quote(table)}")).mappings():
            values = dict(row)
            if table in ("users", "courses"):
                values.pop("institution_id", None)
                values.pop("department", None)  # Migration canonicalizes whitespace/case.
            if table == "courses":
                values.pop("course_type", None)  # Added metadata defaults to academic for legacy records.
                for field in ("program", "batch", "semester_number", "section", "enrollment_mode"):
                    values.pop(field, None)
            if table == "users":
                for field in ("program", "batch", "semester_number", "section", "institutional_id"):
                    values.pop(field, None)
            def stable_value(value):
                if isinstance(value, datetime) and value.tzinfo is not None:
                    return value.astimezone(timezone.utc).isoformat()
                return str(value)
            rows.append(json.dumps(values, sort_keys=True, default=stable_value))
        result[table] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()}
    return result


def run(binary, *args, env=None):
    completed = subprocess.run([str(binary), *map(str, args)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=120)
    if completed.returncode:
        # Raw PostgreSQL diagnostics may contain credentials or academic records.
        raise RuntimeError(f"{Path(binary).name} failed (exit {completed.returncode}); private diagnostics suppressed")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "apply", "verify"])
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--maintenance-confirmed", action="store_true")
    args = parser.parse_args()
    url = dotenv_values(Path(__file__).resolve().parents[1] / ".env.production-migration").get("DATABASE_URL", "")
    parsed = urlsplit(url)
    if parsed.scheme not in ("postgresql", "postgres", "postgresql+psycopg") or not (parsed.hostname or "").endswith(".neon.tech"):
        raise ValueError("Expected the saved Neon PostgreSQL connection")
    sql_url = url.replace("postgresql://", "postgresql+psycopg://", 1).replace("postgres://", "postgresql+psycopg://", 1)
    engine = create_engine(sql_url, connect_args={"connect_timeout": 10})
    folder = args.backup_dir.resolve(strict=True)
    archive = folder / "before-institutions.dump"
    manifest = folder / "verified-backup.json"
    endpoint_digest = hashlib.sha256(f"{parsed.hostname}/{parsed.path}".encode()).hexdigest()

    if args.mode == "prepare":
        if archive.exists() or manifest.exists():
            raise ValueError("Use a new private backup directory; existing backups are never overwritten")
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if "institutions" in inspect(conn).get_table_names():
                raise ValueError("Database already migrated; manual review required")
        remote_env = os.environ.copy()
        remote_env.update(PGHOST=parsed.hostname, PGPORT=str(parsed.port or 5432),
                          PGUSER=unquote(parsed.username or ""), PGPASSWORD=unquote(parsed.password or ""),
                          PGDATABASE=unquote(parsed.path.lstrip("/")),
                          PGSSLMODE=parse_qs(parsed.query).get("sslmode", ["require"])[0],
                          PGCONNECT_TIMEOUT="10")
        run(args.pg_bin / "pg_dump.exe", "--format=custom", "--no-owner", "--no-privileges", "--file", archive, env=remote_env)
        run(args.pg_bin / "pg_restore.exe", "--list", archive)
        print("Backup created. Rehearsing restoration in an isolated local database.", flush=True)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        password = secrets.token_hex(24)
        pwfile = folder / "restore-password.txt"
        pwfile.write_text(password, encoding="utf-8")
        data = folder / "restore-data"
        local_env = os.environ.copy()
        local_env.update(PGHOST="127.0.0.1", PGPORT=str(port), PGUSER="restore_operator", PGPASSWORD=password,
                         PGDATABASE="restorecheck", PGSSLMODE="disable")
        started = False
        try:
            run(args.pg_bin / "initdb.exe", "-D", data, "-U", "restore_operator", "--auth=scram-sha-256", "--pwfile", pwfile, "--encoding=UTF8", "--locale=C")
            run(args.pg_bin / "pg_ctl.exe", "-D", data, "-l", folder / "restore-server.log", "-o", f"-h 127.0.0.1 -p {port}", "-w", "start")
            started = True
            run(args.pg_bin / "createdb.exe", "restorecheck", env=local_env)
            run(args.pg_bin / "pg_restore.exe", "--no-owner", "--no-privileges", "--exit-on-error", "--dbname=restorecheck", archive, env=local_env)
            local_engine = create_engine(f"postgresql+psycopg://restore_operator:{password}@127.0.0.1:{port}/restorecheck")
            with local_engine.connect() as conn:
                tables = inspect(conn).get_table_names()
                before = fingerprint(conn, tables)
                conn.rollback()
                # Import does not connect to or mutate the production database.
                from scripts.migrate_institutions import migrate
                inst_id = migrate(conn, "HITAM", "hitam.org")
                assert fingerprint(conn, tables) == before, "Rehearsal changed existing records"
                for table in ("users", "courses"):
                    assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE institution_id IS NULL OR institution_id != :id"), {"id": inst_id}).scalar() == 0
                conn.commit()
                assert migrate(conn, "HITAM", "hitam.org") == inst_id
                conn.commit()
            local_engine.dispose()
            manifest.write_text(json.dumps({"endpoint_sha256": endpoint_digest, "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                                            "tables": tables, "fingerprints": before, "restore_and_migration_verified": True}, indent=2), encoding="utf-8")
            print("Full restore and PostgreSQL migration rehearsal passed. Existing records preserved.", flush=True)
        finally:
            if started:
                run(args.pg_bin / "pg_ctl.exe", "-D", data, "-m", "fast", "-w", "stop")
        return

    verified = json.loads(manifest.read_text(encoding="utf-8"))
    if (not verified.get("restore_and_migration_verified") or verified["endpoint_sha256"] != endpoint_digest
            or verified["archive_sha256"] != hashlib.sha256(archive.read_bytes()).hexdigest()):
        raise ValueError("Backup verification failed")
    if args.mode == "verify":
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            assert fingerprint(conn, verified["tables"]) == verified["fingerprints"], "Existing records differ from backup"
            for table in ("users", "courses"):
                assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE institution_id IS NULL")).scalar() == 0
        print("Production records and credentials match the verified backup; institution assignment is complete.")
        return
    if not args.maintenance_confirmed:
        raise ValueError("Public maintenance mode must be confirmed before applying")
    from scripts.migrate_institutions import migrate
    with engine.connect() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '15s'"))
        conn.execute(text("SET LOCAL statement_timeout = '60s'"))
        quote = conn.dialect.identifier_preparer.quote
        conn.execute(text("LOCK TABLE " + ", ".join(quote(t) for t in verified["tables"]) + " IN ACCESS EXCLUSIVE MODE"))
        if fingerprint(conn, verified["tables"]) != verified["fingerprints"]:
            raise ValueError("Database changed since backup; take a new backup before upgrading")
        if conn.execute(text("SELECT count(*) FROM users WHERE lower(email) NOT LIKE '%@hitam.org'")).scalar():
            raise ValueError("Unexpected institution ownership")
        inst_id = migrate(conn, "HITAM", "hitam.org")
        assert fingerprint(conn, verified["tables"]) == verified["fingerprints"], "Existing records changed"
        for table in ("users", "courses"):
            assert conn.execute(text(f"SELECT count(*) FROM {table} WHERE institution_id IS NULL OR institution_id != :id"), {"id": inst_id}).scalar() == 0
        conn.commit()
    print("Production migration committed. Existing accounts, passwords and academic records preserved.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Upgrade stopped:", type(exc).__name__, "(private details suppressed). Do not promote the new release.")
        sys.exit(1)
