"""Create an Ekeekrta platform operator without exposing an HTTP bootstrap route."""
import argparse
import getpass
from pathlib import Path
import sys

import bcrypt
from email_validator import EmailNotValidError, validate_email
import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.create_first_admin import database_url_from_clipboard, validate_database_url


def create_platform_admin(connection, name: str, email: str, password: str) -> int:
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise ValueError("Use a password with at least 12 characters and at most 72 UTF-8 bytes.")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
    with connection.cursor() as cursor:
        cursor.execute("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE")
        cursor.execute("SELECT id FROM users WHERE lower(email) = lower(%s)", (email,))
        if cursor.fetchone():
            raise ValueError("This email already belongs to an account. Existing accounts are never promoted.")
        cursor.execute(
            "INSERT INTO users (name, email, hashed_password, role, institution_id) "
            "VALUES (%s, %s, %s, 'platform_admin', NULL) RETURNING id",
            (name, email, password_hash),
        )
        return cursor.fetchone()[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an Ekeekrta platform operator in the deployed Neon database.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--clipboard", action="store_true",
                        help="Read the copied Neon connection string privately from the Windows clipboard.")
    args = parser.parse_args()
    try:
        email = validate_email(args.email, check_deliverability=False).normalized.lower()
        name = input("Operator name [Ekeekrta Operator]: ").strip() or "Ekeekrta Operator"
        if len(name) > 120:
            raise ValueError("Name must not exceed 120 characters.")
        if args.clipboard:
            input("Copy the deployed backend's Neon connection string. Return here and press Enter (do not paste): ")
            url = database_url_from_clipboard()
            print("Neon connection string read privately from the clipboard.")
        else:
            url = validate_database_url(getpass.getpass("Neon connection string (hidden): "))
        password = getpass.getpass("Choose an operator password (hidden, minimum 12 characters): ")
        if password != getpass.getpass("Confirm password (hidden): "):
            raise ValueError("Passwords do not match. No account was created.")
        print(f"Create Ekeekrta operator: {name} <{email}>")
        if input("Type CREATE to continue: ").strip() != "CREATE":
            print("Cancelled. No account was created.")
            return 1

        # PostgreSQL requires a native enum value to be committed before it is
        # used. This schema-only statement is idempotent and changes no users.
        with psycopg.connect(url, sslmode="require", connect_timeout=15, autocommit=True) as schema_connection:
            with schema_connection.cursor() as cursor:
                cursor.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'platform_admin'")
        with psycopg.connect(url, sslmode="require", connect_timeout=15) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.users')")
                if cursor.fetchone()[0] is None:
                    raise ValueError("The Ekeekrta backend schema does not exist in this database.")
            create_platform_admin(connection, name, email, password)
        print("Platform operator created.")
        print("Sign in at https://ekeekrta.vercel.app/platform-login")
        return 0
    except (ValueError, EmailNotValidError) as error:
        print(str(error))
    except (KeyboardInterrupt, EOFError):
        print("Setup cancelled. No account was created.")
    except Exception:
        print("Setup failed. Check the Neon connection and deploy the operator schema first. Private details were suppressed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
