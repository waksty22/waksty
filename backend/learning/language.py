"""Personal vocabulary acquisition for Chappie.

Words are not considered usable merely because Gemini knows them. They move
through explicit, persisted learning states supplied by teaching and tests.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

WORD_STATES = ("heard", "imitated", "recognized", "understood", "usable")
STATE_RANK = {state: index for index, state in enumerate(WORD_STATES)}
MAX_WORD_LENGTH = 80
MAX_MEANING_LENGTH = 1000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_word(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Le mot doit être une chaîne de caractères.")
    word = value.strip().casefold()
    word = re.sub(r"^[^\wÀ-ÖØ-öø-ÿ'-]+|[^\wÀ-ÖØ-öø-ÿ'-]+$", "", word)
    if not word or len(word) > MAX_WORD_LENGTH or len(word.split()) != 1:
        raise ValueError("Saisis un seul mot (80 caractères maximum).")
    return word


def init_language_tables(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS personal_vocabulary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            word TEXT NOT NULL,
            meaning TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL CHECK(state IN (
                'heard', 'imitated', 'recognized', 'understood', 'usable'
            )),
            exposure_count INTEGER NOT NULL DEFAULT 1,
            evidence TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, word)
        );
        CREATE INDEX IF NOT EXISTS idx_personal_vocabulary_user_state
        ON personal_vocabulary(user_id, state, word);
    """)


def record_heard_word(
    db: sqlite3.Connection, user_id: str, word: str, evidence: str = "Mot entendu"
) -> dict[str, Any]:
    clean = normalize_word(word)
    now = utc_now()
    db.execute(
        """INSERT INTO personal_vocabulary
           (user_id, word, state, exposure_count, evidence, created_at, updated_at)
           VALUES (?, ?, 'heard', 1, ?, ?, ?)
           ON CONFLICT(user_id, word) DO UPDATE SET
             exposure_count=personal_vocabulary.exposure_count+1,
             evidence=excluded.evidence,
             updated_at=excluded.updated_at""",
        (user_id, clean, evidence[:500], now, now),
    )
    row = db.execute(
        "SELECT * FROM personal_vocabulary WHERE user_id=? AND word=?",
        (user_id, clean),
    ).fetchone()
    return dict(row)


def record_heard_text(
    db: sqlite3.Connection,
    user_id: str,
    text: str,
    evidence: str = "Transcription vocale Gemini Live",
    max_tokens: int = 30,
) -> list[dict[str, Any]]:
    """Record only lexical exposure, never comprehension or mastery."""
    tokens = re.findall(r"[\wÀ-ÖØ-öø-ÿ'-]+", str(text), flags=re.UNICODE)
    recorded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for token in tokens[:max_tokens]:
        try:
            word = normalize_word(token)
        except ValueError:
            continue
        if word in seen:
            continue
        seen.add(word)
        recorded.append(record_heard_word(db, user_id, word, evidence))
    return recorded



def record_explicit_word_teaching(
    db: sqlite3.Connection, user_id: str, text: str,
    evidence: str = "Enseignement explicite de l'utilisateur",
) -> list[dict[str, Any]]:
    """Store explicit word definitions as heard, never as understood."""
    pattern = re.compile(
        r"(?:(?:le\s+)?mot\s+)?"
        r"(?P<word>[A-Za-zÀ-ÖØ-öø-ÿ][\wÀ-ÖØ-öø-ÿ'-]{0,79})"
        r"\s+(?:signifie|veut\s+dire|désigne|correspond\s+à)\s+"
        r"(?P<meaning>[^.!?;\n]{2,500})",
        flags=re.IGNORECASE | re.UNICODE,
    )
    recorded: list[dict[str, Any]] = []
    now = utc_now()
    for match in pattern.finditer(str(text or "")):
        try:
            word = normalize_word(match.group("word"))
        except ValueError:
            continue
        meaning = match.group("meaning").strip(" \t:—-")[:MAX_MEANING_LENGTH]
        if not meaning:
            continue
        db.execute(
            """INSERT INTO personal_vocabulary
               (user_id, word, meaning, state, exposure_count, evidence, created_at, updated_at)
               VALUES (?, ?, ?, 'heard', 1, ?, ?, ?)
               ON CONFLICT(user_id, word) DO UPDATE SET
                 meaning=excluded.meaning,
                 exposure_count=personal_vocabulary.exposure_count+1,
                 evidence=excluded.evidence, updated_at=excluded.updated_at""",
            (user_id, word, meaning, str(evidence)[:500], now, now),
        )
        row = db.execute(
            "SELECT * FROM personal_vocabulary WHERE user_id=? AND word=?",
            (user_id, word),
        ).fetchone()
        if row is not None:
            recorded.append(dict(row))
    return recorded

def advance_word(
    db: sqlite3.Connection,
    user_id: str,
    word: str,
    target_state: str,
    meaning: str = "",
    evidence: str = "",
) -> dict[str, Any]:
    clean = normalize_word(word)
    if target_state not in STATE_RANK:
        raise ValueError("État d'apprentissage invalide.")
    meaning = (meaning or "").strip()
    if len(meaning) > MAX_MEANING_LENGTH:
        raise ValueError("La définition est trop longue.")
    row = db.execute(
        "SELECT * FROM personal_vocabulary WHERE user_id=? AND word=?",
        (user_id, clean),
    ).fetchone()
    if row is None:
        raise ValueError("Ce mot n'a pas encore été entendu par Chappie.")
    current = row["state"]
    if STATE_RANK[target_state] < STATE_RANK[current]:
        raise ValueError("Un mot ne peut pas revenir à un état d'apprentissage antérieur.")
    if STATE_RANK[target_state] > STATE_RANK[current] + 1:
        raise ValueError("La progression doit être validée étape par étape.")
    db.execute(
        """UPDATE personal_vocabulary
           SET state=?, meaning=CASE WHEN ? <> '' THEN ? ELSE meaning END,
               evidence=?, updated_at=?
           WHERE user_id=? AND word=?""",
        (target_state, meaning, meaning, evidence[:500], utc_now(), user_id, clean),
    )
    updated = db.execute(
        "SELECT * FROM personal_vocabulary WHERE user_id=? AND word=?",
        (user_id, clean),
    ).fetchone()
    return dict(updated)


def list_vocabulary(db: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT word, meaning, state, exposure_count, evidence, created_at, updated_at
           FROM personal_vocabulary WHERE user_id=?
           ORDER BY updated_at DESC, word ASC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_usable_words(db: sqlite3.Connection, user_id: str) -> set[str]:
    rows = db.execute(
        "SELECT word FROM personal_vocabulary WHERE user_id=? AND state='usable'",
        (user_id,),
    ).fetchall()
    return {str(row["word"]) for row in rows}


def get_repeatable_words(db: sqlite3.Connection, user_id: str) -> set[str]:
    """Words Chappie has explicitly learned to imitate or beyond."""
    rows = db.execute(
        """SELECT word FROM personal_vocabulary
           WHERE user_id=? AND state IN ('heard', 'imitated', 'recognized', 'understood', 'usable')""",
        (user_id,),
    ).fetchall()
    return {str(row["word"]) for row in rows}


def text_uses_only_allowed_words(text: str, allowed_words: set[str]) -> bool:
    """Return True only when a non-empty transcript uses known lexical items."""
    tokens = re.findall(
        r"[\wÀ-ÖØ-öø-ÿ'-]+", str(text or "").casefold(), flags=re.UNICODE
    )
    return bool(tokens) and all(token in allowed_words for token in tokens)


def gate_spoken_text(
    text: str,
    usable_words: set[str],
    max_words: int | None = None,
) -> str:
    """Filter lexical output; newborn mode can be restricted to isolated words."""
    if not usable_words:
        return ""
    tokens = re.findall(r"[\wÀ-ÖØ-öø-ÿ'-]+|[^\wÀ-ÖØ-öø-ÿ'-]+", text, flags=re.UNICODE)
    output: list[str] = []
    emitted_words = 0
    for token in tokens:
        if re.fullmatch(r"[\wÀ-ÖØ-öø-ÿ'-]+", token, flags=re.UNICODE):
            if token.casefold() in usable_words and (
                max_words is None or emitted_words < max_words
            ):
                output.append(token)
                emitted_words += 1
            else:
                output.append("")
        else:
            output.append(token if max_words is None or emitted_words < max_words else "")
    # Punctuation alone is not a spoken response. If every lexical token
    # was filtered, discard the leftover punctuation as well.
    if emitted_words == 0:
        return ""
    result = "".join(output)
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"\s+([,.!?;:])", r"\1", result)
    result = re.sub(r"([,.!?;:]){2,}", r"\1", result)
    return result.strip(" ,;:-")
