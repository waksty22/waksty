"""Verify Chappie's SQLite memory across a real OS-process restart."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[1]


def _run_python(source: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=BACKEND,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_conversation_memory_survives_complete_process_restart(tmp_path):
    data_dir = tmp_path / "isolated-chappie-data"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(BACKEND),
            "CHAPPIE_STORAGE_BACKEND": "sqlite",
            "CHAPPIE_DATA_DIR": str(data_dir),
            "CHAPPIE_SQLITE_PATH": str(data_dir / "chappie_v16.sqlite3"),
            "CHAPPIE_TIMEZONE": "UTC",
        }
    )
    # Force the test to use only its isolated local SQLite file, even if the
    # developer or CI runner has unrelated Turso settings in its environment.
    for key in (
        "CHAPPIE_ALLOW_TURSO_MIGRATION",
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
        "CHAPPIE_TURSO_CUTOVER_READY",
        "CHAPPIE_TURSO_FRESH_START",
        "CHAPPIE_TURSO_ADOPT_EXISTING_SCHEMA",
    ):
        env.pop(key, None)

    writer = _run_python(
        """
import server
server.init_db()
# Keep this persistence test independent of asynchronous memory extraction.
server.sync_autobiographical_events = lambda db, user_id: None
server.save_conversation_turn(
    "creator",
    "Je t'apprends le mot pomme.",
    "J'ai entendu le mot pomme.",
    source="conversation",
)
""",
        env,
    )
    assert writer.returncode == 0, (
        "Writer process failed.\n"
        f"stdout:\n{writer.stdout}\nstderr:\n{writer.stderr}"
    )

    database = data_dir / "chappie_v16.sqlite3"
    assert database.is_file()
    assert database.stat().st_size > 0

    # This is a distinct Python interpreter after the writer process exited:
    # it cannot reuse the writer's in-memory connection or process state.
    reader = _run_python(
        """
import json
import server

db = server.db_connection()
try:
    rows = db.execute(
        "SELECT role, content FROM conversations "
        "WHERE user_id=? ORDER BY id ASC",
        ("creator",),
    ).fetchall()
    print(json.dumps([
        {"role": row["role"], "content": row["content"]}
        for row in rows
    ], ensure_ascii=False))
finally:
    db.close()
""",
        env,
    )
    assert reader.returncode == 0, (
        "Reader process failed.\n"
        f"stdout:\n{reader.stdout}\nstderr:\n{reader.stderr}"
    )
    persisted = json.loads(reader.stdout.strip().splitlines()[-1])
    assert persisted == [
        {"role": "user", "content": "Je t'apprends le mot pomme."},
        {"role": "assistant", "content": "J'ai entendu le mot pomme."},
    ]
