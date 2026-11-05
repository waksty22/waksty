"""V25 — mémoire autobiographique traçable.

Les épisodes sont des copies indexées des échanges réellement enregistrés.
Aucun résumé généré ni rapprochement sémantique n'est promu en souvenir factuel.
Chaque entrée conserve son identifiant source dans la table conversations.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def init_autobiographical_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS autobiographical_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            source_conversation_id INTEGER NOT NULL,
            actor TEXT NOT NULL CHECK(actor IN ('user', 'assistant')),
            event_type TEXT NOT NULL,
            content TEXT NOT NULL,
            happened_at TEXT NOT NULL,
            importance INTEGER NOT NULL DEFAULT 2
                CHECK(importance BETWEEN 1 AND 5),
            created_at TEXT NOT NULL,
            UNIQUE(user_id, source_conversation_id),
            FOREIGN KEY(source_conversation_id)
                REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_autobio_user_time
            ON autobiographical_events(user_id, happened_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_autobio_user_actor
            ON autobiographical_events(user_id, actor, id DESC);

        CREATE TABLE IF NOT EXISTS autobiographical_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            source_event_id INTEGER NOT NULL,
            target_event_id INTEGER NOT NULL,
            relation_type TEXT NOT NULL
                CHECK(relation_type IN ('same_dialogue_turn')),
            created_at TEXT NOT NULL,
            UNIQUE(user_id, source_event_id, target_event_id, relation_type),
            FOREIGN KEY(source_event_id)
                REFERENCES autobiographical_events(id) ON DELETE CASCADE,
            FOREIGN KEY(target_event_id)
                REFERENCES autobiographical_events(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_autobio_links_user
            ON autobiographical_links(user_id, source_event_id);
    """)


def sync_autobiographical_events(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = 500,
) -> dict[str, int]:
    """Indexe idempotemment les conversations absentes du journal autobiographique."""
    limit = max(1, min(int(limit), 2000))
    rows = db.execute(
        """
        SELECT c.id, c.role, c.content, c.created_at
        FROM conversations c
        LEFT JOIN autobiographical_events e
          ON e.user_id=c.user_id
         AND e.source_conversation_id=c.id
        WHERE c.user_id=? AND e.id IS NULL
        ORDER BY c.id ASC
        LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()

    inserted = 0
    for row in rows:
        actor = str(row["role"])
        content = str(row["content"] or "").strip()
        if actor not in {"user", "assistant"} or not content:
            continue
        event_type = "user_statement" if actor == "user" else "chappie_response"
        importance = 3 if actor == "user" else 1
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO autobiographical_events
                (user_id, source_conversation_id, actor, event_type,
                 content, happened_at, importance, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, int(row["id"]), actor, event_type, content[:8000],
             str(row["created_at"]), importance, str(row["created_at"])),
        )
        inserted += max(0, cursor.rowcount)

    # Relie uniquement les deux messages qui partagent exactement l'horodatage
    # créé par save_conversation_turn : c'est un lien de dialogue, pas de sens.
    db.execute(
        """
        INSERT OR IGNORE INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        SELECT u.user_id, u.id, a.id, 'same_dialogue_turn', u.created_at
        FROM autobiographical_events u
        JOIN autobiographical_events a
          ON a.user_id=u.user_id
         AND a.happened_at=u.happened_at
         AND a.actor='assistant'
        WHERE u.user_id=? AND u.actor='user'
        """,
        (user_id,),
    )
    db.commit()
    total = db.execute(
        "SELECT COUNT(*) FROM autobiographical_events WHERE user_id=?",
        (user_id,),
    ).fetchone()[0]
    links = db.execute(
        "SELECT COUNT(*) FROM autobiographical_links WHERE user_id=?",
        (user_id,),
    ).fetchone()[0]
    return {"inserted": inserted, "total_events": int(total), "dialogue_links": int(links)}


def list_autobiographical_events(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = 30,
    before_id: int | None = None,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    params: list[Any] = [user_id]
    where = "user_id=?"
    if before_id is not None:
        where += " AND id < ?"
        params.append(max(0, int(before_id)))
    params.append(limit)
    rows = db.execute(
        f"""
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE {where}
        ORDER BY id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def search_autobiographical_events(
    db: sqlite3.Connection,
    user_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    query = str(query or "").strip()[:200]
    if not query:
        return []
    limit = max(1, min(int(limit), 30))
    # Échappement des jokers LIKE : recherche littérale, sans interprétation.
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.execute(
        """
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE user_id=? AND content LIKE ? ESCAPE '\\' COLLATE NOCASE
        ORDER BY importance DESC, id DESC
        LIMIT ?
        """,
        (user_id, f"%{escaped}%", limit),
    ).fetchall()
    return [dict(row) for row in rows]


def autobiographical_statistics(
    db: sqlite3.Connection,
    user_id: str,
) -> dict[str, int]:
    row = db.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN actor='user' THEN 1 ELSE 0 END) AS user_events,
               SUM(CASE WHEN actor='assistant' THEN 1 ELSE 0 END) AS chappie_events
        FROM autobiographical_events WHERE user_id=?
        """,
        (user_id,),
    ).fetchone()
    links = db.execute(
        "SELECT COUNT(*) FROM autobiographical_links WHERE user_id=?",
        (user_id,),
    ).fetchone()[0]
    return {
        "total_events": int(row["total"] or 0),
        "user_events": int(row["user_events"] or 0),
        "chappie_events": int(row["chappie_events"] or 0),
        "dialogue_links": int(links or 0),
    }
