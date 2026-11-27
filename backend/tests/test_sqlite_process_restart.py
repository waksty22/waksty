"""Verify Chappie's conversation memory across a real OS-process restart."""
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


def test_chat_and_gemini_live_memory_survive_complete_process_restart(tmp_path):
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
server.sync_autobiographical_events = lambda db, user_id, commit=True, **kwargs: None
server.save_conversation_turn(
    "creator", "Je t'apprends le mot pomme.",
    "J'ai entendu le mot pomme.", source="conversation",
)
server.save_conversation_turn(
    "creator", "En direct, je te montre une pomme.",
    "Je me souviens du mot pomme.", source="gemini_live",
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

    reader = _run_python(
        """
import json
import server
with server.db_connection() as db:
    rows = db.execute(
        "SELECT role, content FROM conversations "
        "WHERE user_id=? ORDER BY id ASC",
        ("creator",),
    ).fetchall()
    sources = db.execute(
        "SELECT kind FROM journal WHERE user_id=? ORDER BY id ASC",
        ("creator",),
    ).fetchall()
print(json.dumps({
    "rows": [{"role": row["role"], "content": row["content"]} for row in rows],
    "sources": [row["kind"] for row in sources],
}, ensure_ascii=False))
""",
        env,
    )
    assert reader.returncode == 0, (
        "Reader process failed.\n"
        f"stdout:\n{reader.stdout}\nstderr:\n{reader.stderr}"
    )
    persisted = json.loads(reader.stdout.strip().splitlines()[-1])
    assert persisted == {
        "rows": [
            {"role": "user", "content": "Je t'apprends le mot pomme."},
            {"role": "assistant", "content": "J'ai entendu le mot pomme."},
            {"role": "user", "content": "En direct, je te montre une pomme."},
            {"role": "assistant", "content": "Je me souviens du mot pomme."},
        ],
        "sources": ["conversation", "gemini_live"],
    }
