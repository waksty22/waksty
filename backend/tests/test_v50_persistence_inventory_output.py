from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.inspect_persistence_inventory import (
    render_report,
    write_report_no_clobber,
)


def _make_database(path: Path) -> bytes:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, content TEXT)")
    connection.execute("INSERT INTO memories(content) VALUES ('private sentinel')")
    connection.commit()
    connection.close()
    return path.read_bytes()


def test_output_equal_to_database_is_rejected_without_changing_database(
    tmp_path: Path,
) -> None:
    database = tmp_path / "chappie.sqlite3"
    before = _make_database(database)

    with pytest.raises(ValueError, match="database"):
        write_report_no_clobber(database, database, '{"report": true}\n')

    assert database.read_bytes() == before
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    assert connection.execute("SELECT content FROM memories").fetchone()[0] == (
        "private sentinel"
    )
    connection.close()


def test_output_symlink_to_database_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "chappie.sqlite3"
    before = _make_database(database)
    alias = tmp_path / "report.json"
    try:
        alias.symlink_to(database)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks are unavailable on this platform")

    with pytest.raises(ValueError, match="database"):
        write_report_no_clobber(alias, database, '{"report": true}\n')

    assert database.read_bytes() == before


def test_output_hardlink_to_database_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "chappie.sqlite3"
    before = _make_database(database)
    alias = tmp_path / "report.json"
    try:
        alias.hardlink_to(database)
    except (OSError, NotImplementedError):
        pytest.skip("Hard links are unavailable on this platform")

    with pytest.raises(ValueError, match="database"):
        write_report_no_clobber(alias, database, '{"report": true}\n')

    assert database.read_bytes() == before


def test_existing_report_is_never_overwritten(tmp_path: Path) -> None:
    database = tmp_path / "chappie.sqlite3"
    _make_database(database)
    output = tmp_path / "report.json"
    output.write_text("keep existing report", encoding="utf-8")

    with pytest.raises(FileExistsError, match="overwrite"):
        write_report_no_clobber(output, database, '{"report": true}\n')

    assert output.read_text(encoding="utf-8") == "keep existing report"


def test_new_report_is_valid_json_with_one_real_trailing_newline() -> None:
    rendered = render_report({"read_only": True, "rows": 1})

    assert rendered.endswith("\n")
    assert not rendered.endswith("\\n")
    assert json.loads(rendered) == {"read_only": True, "rows": 1}


def test_new_report_is_created_without_clobbering(tmp_path: Path) -> None:
    database = tmp_path / "chappie.sqlite3"
    _make_database(database)
    output = tmp_path / "reports" / "inventory.json"

    write_report_no_clobber(
        output, database, render_report({"read_only": True})
    )

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "read_only": True
    }
    assert output.stat().st_mode & 0o777 == 0o600
