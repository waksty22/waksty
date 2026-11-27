"""V25 — mémoire autobiographique traçable.

Les épisodes sont des copies indexées des échanges réellement enregistrés.
Aucun résumé généré ni rapprochement sémantique n'est promu en souvenir factuel.
Chaque entrée conserve son identifiant source dans la table conversations.
"""
from __future__ import annotations

import heapq
import re
import sqlite3
from datetime import datetime, timezone
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

def _timestamp_sort_key(value: Any) -> float:
    """Convertit un horodatage ISO en instant comparable, quel que soit son offset."""
    if not isinstance(value, str) or not value.strip():
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return float("-inf")


def _is_valid_autobiographical_event(item: dict[str, Any]) -> bool:
    """Reject malformed persisted episodes before lexical ranking."""
    for field in ("id", "source_conversation_id"):
        value = item.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            return False
    if item.get("actor") not in {"user", "assistant"}:
        return False
    if not isinstance(item.get("event_type"), str) or not item["event_type"].strip():
        return False
    if not isinstance(item.get("content"), str) or not item["content"].strip():
        return False
    if not isinstance(item.get("happened_at"), str) or not item["happened_at"].strip():
        return False
    if _timestamp_sort_key(item["happened_at"]) == float("-inf"):
        return False
    importance = item.get("importance")
    return (
        isinstance(importance, int)
        and not isinstance(importance, bool)
        and 1 <= importance <= 5
    )



def _source_matches_event(
    db: sqlite3.Connection, user_id: str, item: dict[str, Any]
) -> bool:
    """Verify that a copied episode still matches its same-user source message."""
    table = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversations'"
    ).fetchone()
    # Lightweight unit callers may exercise this module without the source table.
    if table is None:
        return True
    source = db.execute(
        """
        SELECT user_id, role, content, created_at
        FROM conversations
        WHERE id=?
        """,
        (item.get("source_conversation_id"),),
    ).fetchone()
    if source is None:
        return False
    content = source["content"]
    return (
        source["user_id"] == user_id
        and source["role"] == item.get("actor")
        and isinstance(content, str)
        and content.strip()[:8000] == item.get("content")
        and source["created_at"] == item.get("happened_at")
    )


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
    conversation_ids: list[int] | tuple[int, ...] | None = None,
    include_counts: bool = True,
) -> dict[str, int]:
    """Indexe les conversations manquantes, ou les sources ciblées d'un tour."""
    user_id = _validated_user_id(user_id)
    limit = _bounded_limit(limit, 2000)
    if not isinstance(commit, bool):
        raise ValueError("commit doit être un booléen.")
    if not isinstance(include_counts, bool):
        raise ValueError("include_counts doit être un booléen.")
    source_filter = ""
    params: list[Any] = [user_id]
    if conversation_ids is not None:
        if not isinstance(conversation_ids, (list, tuple)) or len(conversation_ids) > 2000:
            raise ValueError("La liste des conversations à indexer est invalide.")
        validated_ids: list[int] = []
        for conversation_id in conversation_ids:
            validated_ids.append(
                _validated_integer(conversation_id, "Identifiant de conversation")
            )
        validated_ids = list(dict.fromkeys(validated_ids))
        if validated_ids:
            source_filter = " AND c.id IN (" + ",".join("?" for _ in validated_ids) + ")"
            params.extend(dict.fromkeys(validated_ids))
        else:
            source_filter = " AND 0"
    params.append(limit)
    rows = db.execute(
        f"""
        SELECT c.id, c.role, c.content, c.created_at
        FROM conversations c
        LEFT JOIN autobiographical_events e
          ON e.user_id=c.user_id
         AND e.source_conversation_id=c.id
        WHERE c.user_id=? AND e.id IS NULL
          AND c.role IN ('user', 'assistant')
          AND typeof(c.content)='text' AND length(trim(c.content)) > 0
          AND typeof(c.created_at)='text' AND length(trim(c.created_at)) > 0
          AND julianday(c.created_at) IS NOT NULL
          {source_filter}
        ORDER BY c.id ASC
        LIMIT ?
        """,
        params,
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

    # Un enregistrement ciblé ne doit examiner que les réponses nouvellement
    # indexées : reparcourir tout l'historique à chaque tour rendrait le coût
    # cumulé quadratique. Le rattrapage sans filtre conserve le balayage complet.
    link_filter = ""
    link_params: list[Any] = [user_id]
    if conversation_ids is not None:
        target_ids = list(dict.fromkeys(validated_ids))
        if not target_ids:
            link_filter = " AND 0"
        else:
            placeholders = ",".join("?" for _ in target_ids)
            link_filter = f" AND assistant_message.id IN ({placeholders})"
            link_params.extend(target_ids)

    # Relie uniquement deux messages adjacents dans l'historique de CE
    # user. Les IDs de conversations sont globaux : un message d'un autre
    # utilisateur peut légitimement se glisser entre les deux IDs.
    # L'horodatage doit aussi correspondre pour éviter de relier deux tours.
    db.execute(
        f"""
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
          {link_filter}
          AND COALESCE((
              SELECT previous_same_user.role
              FROM conversations previous_same_user
              WHERE previous_same_user.user_id=user_message.user_id
                AND previous_same_user.id < user_message.id
              ORDER BY previous_same_user.id DESC
              LIMIT 1
          ), '') != 'user'
          AND NOT EXISTS (
              SELECT 1
              FROM conversations between_turn
              WHERE between_turn.user_id=user_message.user_id
                AND between_turn.id > user_message.id
                AND between_turn.id < assistant_message.id
          )
        """,
        link_params,
    )
    if commit:
        db.commit()
    if not include_counts:
        return {"inserted": inserted}
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
        cursor = db.execute(
            """
            SELECT julianday(happened_at) AS sort_time
            FROM autobiographical_events
            WHERE user_id=? AND id=?
            """,
            (user_id, before_id),
        ).fetchone()
        # A cursor must belong to this user. Unknown/foreign cursors return
        # no rows rather than silently restarting at the first page.
        if cursor is None:
            return []
        cursor_time = cursor["sort_time"]
        cursor_time = float(cursor_time) if cursor_time is not None else -1.0
        where += (
            " AND (COALESCE(julianday(happened_at), -1.0) < ?"
            " OR (COALESCE(julianday(happened_at), -1.0) = ? AND id < ?))"
        )
        params.extend([cursor_time, cursor_time, before_id])
    params.append(limit)
    rows = db.execute(
        f"""
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE {where}
          AND typeof(id)='integer' AND id > 0
          AND typeof(source_conversation_id)='integer' AND source_conversation_id > 0
          AND actor IN ('user', 'assistant')
          AND typeof(event_type)='text' AND length(trim(event_type)) > 0
          AND typeof(content)='text' AND length(trim(content)) > 0
          AND typeof(happened_at)='text' AND julianday(happened_at) IS NOT NULL
          AND typeof(importance)='integer' AND importance BETWEEN 1 AND 5
        ORDER BY julianday(happened_at) DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        item for row in rows
        if _is_valid_autobiographical_event(item := dict(row))
        and _source_matches_event(db, user_id, item)
    ]


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

    # Scan the complete autobiographical history in bounded keyset pages.
    # Keep only the best requested results in memory so recall remains usable
    # for very long-lived users without loading the entire journal at once.
    ranked: list[tuple[float, int, float, int, dict[str, Any]]] = []
    page_size = 500
    last_seen_id: int | None = None
    while True:
        if last_seen_id is None:
            rows = db.execute(
                """
                SELECT id, source_conversation_id, actor, event_type, content,
                       happened_at, importance
                FROM autobiographical_events
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, page_size),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT id, source_conversation_id, actor, event_type, content,
                       happened_at, importance
                FROM autobiographical_events
                WHERE user_id=? AND id < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, last_seen_id, page_size),
            ).fetchall()
        if not rows:
            break
        for row in rows:
            item = dict(row)
            if not _is_valid_autobiographical_event(item):
                continue
            normalized_content = _normalize_search_text(item["content"])
            content_tokens = set(normalized_content.split())
            if not content_tokens:
                continue
            # Match complete normalized tokens only: substring matches can create
            # false autobiographical recalls (e.g. "art" inside "partage").
            matched_tokens = set(tokens) & content_tokens
            present = len(matched_tokens)
            if not present:
                continue
            if not _source_matches_event(db, user_id, item):
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
            rank = (
                score,
                importance,
                _timestamp_sort_key(item.get("happened_at")),
                int(item.get("id") or 0),
                item,
            )
            if len(ranked) < limit:
                heapq.heappush(ranked, rank)
            elif rank[:4] > ranked[0][:4]:
                heapq.heapreplace(ranked, rank)
        last_seen_id = int(rows[-1]["id"])

    ranked.sort(key=lambda rank: rank[:4], reverse=True)
    selected = [rank[4] for rank in ranked]
    # Add the paired Chappie reply for a matching user statement, but only via
    # the explicit same-dialogue-turn relation stored at ingestion time.
    selected_ids = {int(item["id"]) for item in selected}
    # Preserve the response paired with the strongest matching user episode.
    # A full result page must not silently discard dialogue context: reserve a
    # slot by evicting the lowest-ranked *other* episode only when necessary.
    preferred_user_event = next(
        (
            item for item in selected
            if item.get("actor") == "user"
            and isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
        ),
        None,
    )
    if preferred_user_event is not None and limit > 1:
        source_event_id = int(preferred_user_event["id"])
        linked = db.execute(
            """
            SELECT a.id, a.source_conversation_id, a.actor, a.event_type,
                   a.content, a.happened_at, a.importance
            FROM autobiographical_links l
            JOIN autobiographical_events a
              ON a.id=l.target_event_id AND a.user_id=l.user_id
            WHERE l.user_id=? AND l.relation_type='same_dialogue_turn'
              AND l.source_event_id=?
            ORDER BY a.id DESC
            LIMIT 1
            """,
            (user_id, source_event_id),
        ).fetchall()
        for row in linked:
            item = dict(row)
            if (
                not _is_valid_autobiographical_event(item)
                or not _source_matches_event(db, user_id, item)
            ):
                continue
            if int(item["id"]) in selected_ids:
                continue
            item["relevance_score"] = 0.0
            item["matched_terms"] = []
            item["dialogue_context"] = True
            if len(selected) >= limit:
                # The preferred source is first among ranked results; never
                # evict it. Keep the highest-ranked context within the bound.
                evict_index = next(
                    (
                        index for index in range(len(selected) - 1, -1, -1)
                        if int(selected[index].get("id") or 0) != source_event_id
                    ),
                    None,
                )
                if evict_index is None:
                    break
                selected.pop(evict_index)
            selected.append(item)
            selected_ids.add(int(item["id"]))
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
        SELECT id, source_conversation_id, actor, event_type, content,
               happened_at, importance
        FROM autobiographical_events
        WHERE user_id=? AND id=?
        """,
        (user_id, event_id),
    ).fetchone()
    if (
        source is None
        or not _is_valid_autobiographical_event(dict(source))
        or not _source_matches_event(db, user_id, dict(source))
    ):
        return []

    def terms(value: str) -> set[str]:
        return {
            token for token in _normalize_search_text(value).split()
            if len(token) >= 3 and token not in _SEARCH_STOPWORDS
        }

    source_terms = terms(source["content"])
    if not source_terms:
        return []

    candidates: list[tuple[float, float, int, dict[str, Any]]] = []
    page_size = 500
    last_seen_id: int | None = None
    while True:
        if last_seen_id is None:
            rows = db.execute(
                """
                SELECT id, source_conversation_id, actor, event_type, content,
                       happened_at, importance
                FROM autobiographical_events
                WHERE user_id=? AND id<>?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, event_id, page_size),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT id, source_conversation_id, actor, event_type, content,
                       happened_at, importance
                FROM autobiographical_events
                WHERE user_id=? AND id<>? AND id < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, event_id, last_seen_id, page_size),
            ).fetchall()
        if not rows:
            break
        for row in rows:
            item = dict(row)
            if not _is_valid_autobiographical_event(item):
                continue
            candidate_terms = terms(item["content"])
            common = sorted(source_terms & candidate_terms)
            # Require at least two meaningful shared terms to reduce weak matches.
            if len(common) < 2:
                continue
            if not _source_matches_event(db, user_id, item):
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
            rank = (
                score,
                _timestamp_sort_key(item.get("happened_at")),
                int(item.get("id") or 0),
                item,
            )
            if len(candidates) < limit:
                heapq.heappush(candidates, rank)
            elif rank[:3] > candidates[0][:3]:
                heapq.heapreplace(candidates, rank)
        last_seen_id = int(rows[-1]["id"])

    candidates.sort(key=lambda rank: rank[:3], reverse=True)
    return [rank[3] for rank in candidates]

def autobiographical_statistics(
    db: sqlite3.Connection,
    user_id: str,
) -> dict[str, int]:
    user_id = _validated_user_id(user_id)
    # Statistics must describe recall-eligible episodes, not merely raw rows.
    # This keeps dashboards honest when legacy/corrupt records are rejected by
    # list and search. Links count only when both endpoints are valid episodes.
    row = db.execute(
        """
        WITH valid_events AS (
            SELECT id, user_id, actor
            FROM autobiographical_events
            WHERE user_id=?
              AND typeof(id)='integer' AND id > 0
              AND typeof(source_conversation_id)='integer'
              AND source_conversation_id > 0
              AND actor IN ('user', 'assistant')
              AND typeof(event_type)='text' AND length(trim(event_type)) > 0
              AND typeof(content)='text' AND length(trim(content)) > 0
              AND typeof(happened_at)='text'
              AND julianday(happened_at) IS NOT NULL
              AND typeof(importance)='integer' AND importance BETWEEN 1 AND 5
        )
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN actor='user' THEN 1 ELSE 0 END) AS user_events,
               SUM(CASE WHEN actor='assistant' THEN 1 ELSE 0 END) AS chappie_events
        FROM valid_events
        """,
        (user_id,),
    ).fetchone()
    links = db.execute(
        """
        WITH valid_events AS (
            SELECT id, user_id
            FROM autobiographical_events
            WHERE user_id=?
              AND typeof(id)='integer' AND id > 0
              AND typeof(source_conversation_id)='integer'
              AND source_conversation_id > 0
              AND actor IN ('user', 'assistant')
              AND typeof(event_type)='text' AND length(trim(event_type)) > 0
              AND typeof(content)='text' AND length(trim(content)) > 0
              AND typeof(happened_at)='text'
              AND julianday(happened_at) IS NOT NULL
              AND typeof(importance)='integer' AND importance BETWEEN 1 AND 5
        )
        SELECT COUNT(*)
        FROM autobiographical_links l
        JOIN valid_events source ON source.id=l.source_event_id
                                AND source.user_id=l.user_id
        JOIN valid_events target ON target.id=l.target_event_id
                                AND target.user_id=l.user_id
        WHERE l.user_id=?
          AND l.relation_type='same_dialogue_turn'
        """,
        (user_id, user_id),
    ).fetchone()[0]
    return {
        "total_events": int(row["total"] or 0),
        "user_events": int(row["user_events"] or 0),
        "chappie_events": int(row["chappie_events"] or 0),
        "dialogue_links": int(links or 0),
    }
