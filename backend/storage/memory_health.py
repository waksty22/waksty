"""Read-only, user-scoped diagnostics for Chappie's durable memory store."""
from __future__ import annotations

from typing import Any


MEMORY_TABLES = (
    "conversations",
    "conversation_summaries",
    "journal",
    "memories",
    "memories_v19",
    "autobiographical_events",
    "autobiographical_links",
)


def inspect_memory_persistence(connection: Any, user_id: str, backend: str) -> dict[str, Any]:
    """Report table presence and per-user row counts without exposing memory contents."""
    user_id = str(user_id or "").strip()
    if not user_id:
        raise ValueError("user_id est obligatoire.")

    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    existing = {
        str(row["name"] if hasattr(row, "keys") else row[0])
        for row in rows
    }

    tables: dict[str, dict[str, Any]] = {}
    for table in MEMORY_TABLES:
        if table not in existing:
            tables[table] = {"exists": False, "rows": None}
            continue
        count = connection.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE user_id=?',
            (user_id,),
        ).fetchone()
        tables[table] = {
            "exists": True,
            "rows": int(count[0]),
        }

    missing = [name for name, info in tables.items() if not info["exists"]]
    return {
        "backend": str(backend),
        "user_scope": "authenticated_user",
        "read_only": True,
        "tables": tables,
        "missing_tables": missing,
        "schema_ready": not missing,
        "conversation_rows": tables["conversations"]["rows"],
        "episodic_memory_rows": tables["memories_v19"]["rows"],
        "legacy_memory_rows": tables["memories"]["rows"],
        "autobiographical_event_rows": tables["autobiographical_events"]["rows"],
        "note": (
            "Les compteurs confirment la présence des données dans le backend "
            "actif, pas à eux seuls leur restauration après redémarrage."
        ),
    }
