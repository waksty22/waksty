"""V25 — mémoire autobiographique traçable.

Les épisodes sont des copies indexées des échanges réellement enregistrés.
Aucun résumé généré ni rapprochement sémantique n'est promu en souvenir factuel.
Chaque entrée conserve son identifiant source dans la table conversations.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any


def _validated_user_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Identifiant utilisateur invalide.")
    value = value.strip()
    if not value or len(value) > 80:
        raise ValueError("Identifiant utilisateur invalide.")
    return value


def _validated_integer(value: Any, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field} doit être un entier supérieur ou égal à {minimum}.")
    return value


def _bounded_limit(value: Any, maximum: int, field: str = "Limite") -> int:
    return min(_validated_integer(value, field), maximum)


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
    commit: bool = True,
) -> dict[str, int]:
    """Indexe idempotemment les conversations absentes du journal autobiographique."""
    user_id = _validated_user_id(user_id)
    limit = _bounded_limit(limit, 2000)
    if not isinstance(commit, bool):
        raise ValueError("commit doit être un booléen.")
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
        actor = row["role"]
        raw_content = row["content"]
        source_id = row["id"]
        created_at = row["created_at"]
        if actor not in {"user", "assistant"} or not isinstance(raw_content, str):
            continue
        if isinstance(source_id, bool) or not isinstance(source_id, int) or source_id < 1:
            continue
        if not isinstance(created_at, str) or not created_at.strip():
            continue
        content = raw_content.strip()
        if not content:
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
            (user_id, source_id, actor, event_type, content[:8000],
             created_at, importance, created_at),
        )
        inserted += max(0, cursor.rowcount)

    # Relie uniquement deux messages adjacents dans l'historique de CE
    # user. Les IDs de conversations sont globaux : un message d'un autre
    # utilisateur peut légitimement se glisser entre les deux IDs.
    # L'horodatage doit aussi correspondre pour éviter de relier deux tours.
    db.execute(
        """
        INSERT OR IGNORE INTO autobiographical_links
            (user_id, source_event_id, target_event_id, relation_type, created_at)
        SELECT u.user_id, u.id, a.id, 'same_dialogue_turn', u.created_at
        FROM conversations user_message
        JOIN conversations assistant_message
          ON assistant_message.user_id=user_message.user_id
         AND assistant_message.id > user_message.id
         AND assistant_message.role='assistant'
         AND assistant_message.created_at=user_message.created_at
        JOIN autobiographical_events u
          ON u.user_id=user_message.user_id
         AND u.source_conversation_id=user_message.id
         AND u.actor='user'
        JOIN autobiographical_events a
          ON a.user_id=assistant_message.user_id
         AND a.source_conversation_id=assistant_message.id
         AND a.actor='assistant'
        WHERE user_message.user_id=?
          AND user_message.role='user'
          AND NOT EXISTS (
              SELECT 1
              FROM conversations previous_same_user
              WHERE previous_same_user.id=user_message.id - 1
                AND previous_same_user.user_id=user_message.user_id
                AND previous_same_user.role='user'
          )
          AND NOT EXISTS (
              SELECT 1
              FROM conversations between_turn
              WHERE between_turn.user_id=user_message.user_id
                AND between_turn.id > user_message.id
                AND between_turn.id < assistant_message.id
          )
        """,
        (user_id,),
    )
    if commit:
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
    user_id = _validated_user_id(user_id)
    limit = _bounded_limit(limit, 100)
    params: list[Any] = [user_id]
    where = "user_id=?"
    if before_id is not None:
        before_id = _validated_integer(before_id, "Identifiant de pagination")
        where += " AND id < ?"
        params.append(before_id)
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


def _normalize_search_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Le texte à normaliser doit être une chaîne.")
    value = value.casefold().replace("œ", "oe").replace("æ", "ae")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", value))


_SEARCH_STOPWORDS = {
    "alors", "avec", "avoir", "bien", "cela", "cette", "comme", "dans",
    "depuis", "des", "donc", "elle", "elles", "est", "etre", "fait",
    "faire", "fois", "ici", "leur", "leurs", "mais", "meme", "mon",
    "nous", "notre", "pour", "quand", "quel", "quelle", "quelles",
    "quels", "qui", "quoi", "sans", "ses", "son", "sont", "sous",
    "sur", "tous", "tout", "tres", "une", "vers", "vous", "votre",
    "dans", "les", "des", "aux", "par", "pas", "plus", "que", "qui",
    "une", "un", "le", "la", "de", "du", "et", "ou", "en", "a",
}


def search_autobiographical_events(
    db: sqlite3.Connection,
    user_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Retrieve source-grounded episodes by multi-term relevance.

    Matching remains strictly scoped to user_id. Linked assistant replies are
    included only when a matching user episode has an explicit same-turn link;
    the link is labeled as dialogue context, never as semantic confirmation.
    """
    user_id = _validated_user_id(user_id)
    if not isinstance(query, str):
        raise ValueError("La recherche doit être du texte.")
    query = query.strip()[:200]
    if not query:
        return []
    limit = _bounded_limit(limit, 30)
    normalized_query = _normalize_search_text(query)
    tokens = [
        token for token in normalized_query.split()
        if len(token) >= 2 and token not in _SEARCH_STOPWORDS
    ]
    if not tokens:
        return []

    # Bound the candidate scan to recent source episodes for predictable cost.
    rows = db.execute(
        """
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 2000
        """,
        (user_id,),
    ).fetchall()

    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        item = dict(row)
        normalized_content = _normalize_search_text(item.get("content", ""))
        content_tokens = set(normalized_content.split())
        if not content_tokens:
            continue
        # Match complete normalized tokens only: substring matches can create
        # false autobiographical recalls (e.g. "art" inside "partage").
        matched_tokens = set(tokens) & content_tokens
        present = len(matched_tokens)
        if not present:
            continue
        coverage = present / max(1, len(set(tokens)))
        phrase_bonus = 0.35 if normalized_query and normalized_query in normalized_content else 0.0
        importance = max(1, min(5, int(item.get("importance") or 1)))
        # Relevance dominates importance: an unrelated important episode cannot win.
        score = coverage * 4.0 + phrase_bonus + importance * 0.04
        item["relevance_score"] = round(score, 4)
        item["matched_terms"] = [
            token for token in dict.fromkeys(tokens) if token in content_tokens
        ]
        item["dialogue_context"] = False
        ranked.append((score, item))

    ranked.sort(
        key=lambda pair: (
            pair[0],
            int(pair[1].get("importance") or 1),
            str(pair[1].get("happened_at") or ""),
            int(pair[1].get("id") or 0),
        ),
        reverse=True,
    )

    selected = [item for _, item in ranked[:limit]]
    # Add the paired Chappie reply for a matching user statement, but only via
    # the explicit same-dialogue-turn relation stored at ingestion time.
    selected_ids = {int(item["id"]) for item in selected}
    user_event_ids = [
        int(item["id"]) for item in selected if item.get("actor") == "user"
    ]
    if user_event_ids and len(selected) < limit:
        placeholders = ",".join("?" for _ in user_event_ids)
        linked = db.execute(
            f"""
            SELECT a.id, a.source_conversation_id, a.actor, a.event_type,
                   a.content, a.happened_at, a.importance
            FROM autobiographical_links l
            JOIN autobiographical_events a
              ON a.id=l.target_event_id AND a.user_id=l.user_id
            WHERE l.user_id=? AND l.relation_type='same_dialogue_turn'
              AND l.source_event_id IN ({placeholders})
            ORDER BY a.id DESC
            """,
            [user_id, *user_event_ids],
        ).fetchall()
        for row in linked:
            item = dict(row)
            if int(item["id"]) in selected_ids:
                continue
            item["relevance_score"] = 0.0
            item["matched_terms"] = []
            item["dialogue_context"] = True
            selected.append(item)
            selected_ids.add(int(item["id"]))
            if len(selected) >= limit:
                break
    return selected



def find_related_autobiographical_events(
    db: sqlite3.Connection,
    user_id: str,
    event_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Suggest past episodes with shared meaningful terms, never assert causality.

    Results are lexical candidates only. A shared word is not proof that two
    episodes concern the same object, person, or cause. No rows are written.
    """
    user_id = _validated_user_id(user_id)
    event_id = _validated_integer(event_id, "Identifiant d’épisode")
    limit = _bounded_limit(limit, 10)
    source = db.execute(
        """
        SELECT id, content, happened_at
        FROM autobiographical_events
        WHERE user_id=? AND id=?
        """,
        (user_id, event_id),
    ).fetchone()
    if source is None:
        return []

    def terms(value: str) -> set[str]:
        return {
            token for token in _normalize_search_text(value).split()
            if len(token) >= 3 and token not in _SEARCH_STOPWORDS
        }

    source_terms = terms(source["content"])
    if not source_terms:
        return []

    rows = db.execute(
        """
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE user_id=? AND id<>?
        ORDER BY id DESC
        LIMIT 2000
        """,
        (user_id, event_id),
    ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        candidate_terms = terms(item.get("content", ""))
        common = sorted(source_terms & candidate_terms)
        # Require at least two meaningful shared terms to reduce weak matches.
        if len(common) < 2:
            continue
        union = source_terms | candidate_terms
        score = len(common) / max(1, len(union))
        item["shared_terms"] = common[:12]
        item["lexical_similarity"] = round(score, 4)
        item["relation_status"] = "candidate_only"
        item["interpretation_warning"] = (
            "Chevauchement lexical uniquement : identité, causalité et "
            "équivalence entre expériences non confirmées."
        )
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            item["lexical_similarity"],
            str(item.get("happened_at") or ""),
            int(item.get("id") or 0),
        ),
        reverse=True,
    )
    return candidates[:limit]

def autobiographical_statistics(
    db: sqlite3.Connection,
    user_id: str,
) -> dict[str, int]:
    user_id = _validated_user_id(user_id)
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
