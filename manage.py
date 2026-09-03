"""Local-only account administration and SQLite backups; no public admin website."""

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path

from werkzeug.security import generate_password_hash

from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account, PlatformAccountLink
from rrserver.security import password_problem


def backup_database(app, output: Path | None = None) -> Path:
    """Create and verify a consistent, online backup of the SQLite database."""
    if db.engine.dialect.name != "sqlite":
        raise ValueError("backup-database currently supports SQLite databases only")
    database = db.engine.url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        raise ValueError("backup-database requires a file-backed SQLite database path")
    source_path = Path(database).resolve()
    if not source_path.is_file():
        raise ValueError("database file does not exist; start the server before backing it up")

    if output is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output = Path(app.instance_path) / "backups" / f"recadoodle-{timestamp}.sqlite3"
    else:
        output = output.expanduser().resolve()

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"refusing to overwrite existing backup: {output}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".incomplete", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)

    try:
        with (
            closing(sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(temporary)) as destination,
        ):
            source.backup(destination, pages=256)
            result = destination.execute("PRAGMA quick_check").fetchall()
            if result != [("ok",)]:
                raise RuntimeError("SQLite integrity check failed for the new backup")
        try:
            os.link(temporary, output)
        except FileExistsError:
            raise FileExistsError(f"refusing to overwrite existing backup: {output}") from None
    finally:
        temporary.unlink(missing_ok=True)

    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create-developer", "link-platform", "backup-database"])
    parser.add_argument("--username")
    parser.add_argument("--account-id", type=int)
    parser.add_argument("--platform", choices=["0", "1", "2", "3", "4", "5"])
    parser.add_argument("--platform-id")
    parser.add_argument(
        "--output", type=Path, help="backup destination (default: instance/backups)"
    )
    args = parser.parse_args(argv)
    if args.output is not None and args.command != "backup-database":
        parser.error("--output is only valid with backup-database")
    app = create_app(initialize_database=args.command != "backup-database")
    with app.app_context():
        if args.command == "create-developer":
            if not args.username or not 1 <= len(args.username) <= 32:
                parser.error("--username must be 1–32 characters")
            if db.session.scalar(
                db.select(Account).where(db.func.lower(Account.username) == args.username.lower())
            ):
                parser.error("username already exists; no account changed")
            password = getpass("Password (12+ characters): ")
            problem = password_problem(password)
            if problem:
                parser.error(problem)
            if getpass("Confirm password: ") != password:
                parser.error("passwords do not match")
            account = Account(
                username=args.username,
                display_name=args.username,
                password_hash=generate_password_hash(password),
                is_developer=True,
                is_moderator=True,
                token_balance=app.config["STARTING_TOKENS"],
            )
            db.session.add(account)
            db.session.commit()
            print(f"Created developer account {account.id}: {account.username}")
        elif args.command == "link-platform":
            if (
                not args.account_id
                or args.account_id == 1
                or not args.platform
                or not args.platform_id
            ):
                parser.error("supply --account-id (not Coach), --platform and --platform-id")
            if len(args.platform_id) > 128:
                parser.error("platform ID too long")
            account = db.session.get(Account, args.account_id)
            if account is None or not account.password_hash:
                parser.error("account must exist and have a password")
            db.session.merge(
                PlatformAccountLink(
                    platform=args.platform, platform_id=args.platform_id, account_id=account.id
                )
            )
            db.session.commit()
            print("Account picker linked. Password authentication is still required.")
        else:
            try:
                backup_path = backup_database(app, args.output)
            except (OSError, sqlite3.Error, ValueError, RuntimeError) as error:
                parser.error(str(error))
            print(f"Created verified SQLite backup: {backup_path}")


if __name__ == "__main__":
    main()
