import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BACKEND_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from backup_turso import create_backup_archive


def test_archive_member_names_match_authenticated_api_contract(tmp_path):
    database = sqlite3.connect(":memory:")
    database.execute(
        "CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL)"
    )
    database.execute("INSERT INTO memories(content) VALUES (?)", ("isolated test memory",))
    archive_path = tmp_path / "chappie-turso-backup.zip"

    try:
        report = create_backup_archive(
            database,
            archive_path,
            "test-only-backup-encryption-key",
        )

        assert report["encrypted"] is True
        assert report["verified_after_packaging"] is True
        assert archive_path.is_file()

        expected_member = "chappie-turso-backup.json.enc"
        expected_checksum = expected_member + ".sha256"
        with zipfile.ZipFile(archive_path, "r") as archive:
            assert set(archive.namelist()) == {expected_member, expected_checksum}
            checksum_text = archive.read(expected_checksum).decode("ascii").strip()
            assert checksum_text.split()[-1] == expected_member
    finally:
        database.close()



def test_archive_verification_rejects_duplicate_member_names(tmp_path):
    from backup_turso import _extract_expected_archive_members

    archive_path = tmp_path / "duplicate-members.zip"
    destination = tmp_path / "verified"
    destination.mkdir()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("chappie-turso-backup.json.enc", b"first")
        archive.writestr("chappie-turso-backup.json.enc", b"second")
        archive.writestr("chappie-turso-backup.json.enc.sha256", b"checksum")

    with zipfile.ZipFile(archive_path, "r") as archive:
        with pytest.raises(ValueError, match="duplicate"):
            _extract_expected_archive_members(
                archive,
                destination,
                {
                    "chappie-turso-backup.json.enc",
                    "chappie-turso-backup.json.enc.sha256",
                },
            )

    assert list(destination.iterdir()) == []
