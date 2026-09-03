import sqlite3

import pytest

from manage import backup_database
from rrserver import create_app
from rrserver.extensions import db
from rrserver.models import Account


@pytest.fixture()
def management_app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'management.sqlite3'}",
            "JWT_SECRET": "test-secret-longer-than-thirty-two-bytes",
            "TRUSTED_HOSTS": None,
        }
    )


def test_backup_database_copies_committed_data_and_passes_integrity_check(management_app, tmp_path):
    output = tmp_path / "exports" / "server-backup.sqlite3"
    with management_app.app_context():
        db.session.add(
            Account(
                username="BackupPlayer",
                display_name="Backup Player",
                password_hash="not-a-real-password-hash",
            )
        )
        db.session.commit()

        assert backup_database(management_app, output) == output.resolve()

    with sqlite3.connect(output) as backup:
        assert backup.execute("PRAGMA quick_check").fetchone() == ("ok",)
        assert backup.execute(
            "SELECT display_name FROM account WHERE username = ?", ("BackupPlayer",)
        ).fetchone() == ("Backup Player",)


def test_backup_database_refuses_to_overwrite_existing_file(management_app, tmp_path):
    output = tmp_path / "existing.sqlite3"
    output.write_bytes(b"keep this data")

    with management_app.app_context(), pytest.raises(FileExistsError, match="refusing"):
        backup_database(management_app, output)

    assert output.read_bytes() == b"keep this data"
    assert list(tmp_path.glob("*.incomplete")) == []
