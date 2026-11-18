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


def _require_user_id(user_id: str) -> str:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("Identifiant utilisateur invalide.")
    return user_id.strip()


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
    user_id = _require_user_id(user_id)
    clean = normalize_word(word)
    if not isinstance(evidence, str):
        raise ValueError("La preuve d'exposition doit être du texte.")
    now = utc_now()
    db.execute(
        """INSERT INTO personal_vocabulary
           (user_id, word, state, exposure_count, evidence, created_at, updated_at)
           VALUES (?, ?, 'heard', 1, ?, ?, ?)
           ON CONFLICT(user_id, word) DO UPDATE SET
             exposure_count=CASE
                 WHEN typeof(personal_vocabulary.exposure_count)='integer'
                  AND personal_vocabulary.exposure_count < 9223372036854775807
                 THEN personal_vocabulary.exposure_count+1
                 ELSE personal_vocabulary.exposure_count
             END,
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
    user_id = _require_user_id(user_id)
    if not isinstance(text, str):
        raise ValueError("Le texte entendu doit être une chaîne de caractères.")
    if not isinstance(evidence, str):
        raise ValueError("La preuve d'exposition doit être du texte.")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1:
        raise ValueError("La limite de mots doit être un entier positif.")
    tokens = re.findall(r"[\wÀ-ÖØ-öø-ÿ'-]+", text, flags=re.UNICODE)
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
    user_id = _require_user_id(user_id)
    if not isinstance(text, str):
        raise ValueError("Le texte enseigné doit être une chaîne de caractères.")
    if not isinstance(evidence, str):
        raise ValueError("La preuve d'enseignement doit être du texte.")
    pattern = re.compile(
        r"(?:(?:le\s+)?mot\s+)?"
        r"(?P<word>[A-Za-zÀ-ÖØ-öø-ÿ][\wÀ-ÖØ-öø-ÿ'-]{0,79})"
        r"\s+(?:signifie|veut\s+dire|désigne|correspond\s+à)\s+"
        r"(?P<meaning>[^.!?;\n]{2,500})",
        flags=re.IGNORECASE | re.UNICODE,
    )
    recorded: list[dict[str, Any]] = []
    now = utc_now()
    uncertainty_prefix = re.compile(
        r"\b(?:je\s+(?:ne\s+)?sais\s+pas|"
        r"je\s+me\s+demande|"
        r"je\s+ne\s+suis\s+pas\s+(?:s[uû]r(?:e)?|certain(?:e)?)|"
        r"je\s+doute|"
        r"peut[- ]être|"
        r"je\s+(?:crois|pense)\s+que|"
        r"il\s+para[iî]t\s+que|"
        r"on\s+m['’]a\s+dit\s+que|"
        r"si\b|"
        r"supposons\s+que|imaginons\s+que|admettons\s+que|"
        r"dans\s+l['’]hypothèse\s+où|au\s+cas\s+où)\b",
        flags=re.IGNORECASE | re.UNICODE,
    )
    # Also inspect the whole sentence: uncertainty or disputed attribution
    # can follow the definition connector ("coq signifie peut-être...").
    uncertainty_sentence = re.compile(
        r"\b(?:ce\s+n['’]est\s+pas\s+vrai\s+que|"
        r"il\s+est\s+faux\s+que|c['’]est\s+faux\s+que|"
        r"on\s+(?:prétend|affirme|raconte)\s+que|"
        r"selon\s+\w+|"
        r"peut[- ]être|probablement|possiblement|éventuellement)\b",
        flags=re.IGNORECASE | re.UNICODE,
    )
    for match in pattern.finditer(text):
        # A question or an explicitly uncertain statement is not a lesson.
        # Evaluate only the sentence containing this candidate, so an
        # unrelated question earlier in the same message does not suppress it.
        sentence_start = max(
            text.rfind(mark, 0, match.start()) for mark in ".!?;\n"
        ) + 1
        sentence_end_candidates = [
            position for mark in ".!?;\n"
            if (position := text.find(mark, match.end())) != -1
        ]
        sentence_end = min(sentence_end_candidates) if sentence_end_candidates else len(text)
        sentence = text[sentence_start:sentence_end + 1]
        prefix = text[sentence_start:match.start()]
        if (
            "?" in sentence
            or uncertainty_prefix.search(prefix)
            or uncertainty_sentence.search(sentence)
        ):
            continue
        try:
            word = normalize_word(match.group("word"))
        except ValueError:
            continue
        meaning = match.group("meaning").strip(" \t:—-")[:MAX_MEANING_LENGTH]
        # A negated definition may otherwise be re-parsed from the negation
        # particle itself (e.g. "coq ne signifie pas...") or accepted as
        # a positive definition whose meaning starts with "pas".
        if word in {"ne", "n'", "pas"} or re.match(
            r"^(?:pas|plus|jamais|aucun(?:e)?|nul(?:le)?)\\b",
            meaning,
            flags=re.IGNORECASE | re.UNICODE,
        ):
            continue
        if not meaning:
            continue
        db.execute(
            """INSERT INTO personal_vocabulary
               (user_id, word, meaning, state, exposure_count, evidence, created_at, updated_at)
               VALUES (?, ?, ?, 'heard', 1, ?, ?, ?)
               ON CONFLICT(user_id, word) DO UPDATE SET
                 meaning=excluded.meaning,
                 evidence=excluded.evidence, updated_at=excluded.updated_at""",
            (user_id, word, meaning, evidence[:500], now, now),
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
    user_id = _require_user_id(user_id)
    clean = normalize_word(word)
    if not isinstance(target_state, str) or target_state not in STATE_RANK:
        raise ValueError("État d'apprentissage invalide.")
    if not isinstance(meaning, str):
        raise ValueError("La définition doit être du texte.")
    if not isinstance(evidence, str):
        raise ValueError("La preuve de progression doit être du texte.")
    meaning = meaning.strip()
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
    user_id = _require_user_id(user_id)
    rows = db.execute(
        """SELECT word, meaning, state, exposure_count, evidence, created_at, updated_at
           FROM personal_vocabulary WHERE user_id=?
           ORDER BY updated_at DESC, word ASC""",
        (user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_usable_words(db: sqlite3.Connection, user_id: str) -> set[str]:
    user_id = _require_user_id(user_id)
    rows = db.execute(
        "SELECT word FROM personal_vocabulary WHERE user_id=? AND state='usable'",
        (user_id,),
    ).fetchall()
    return {str(row["word"]) for row in rows}


def get_repeatable_words(db: sqlite3.Connection, user_id: str) -> set[str]:
    """Words Chappie has explicitly learned to imitate or beyond."""
    user_id = _require_user_id(user_id)
    rows = db.execute(
        """SELECT word FROM personal_vocabulary
           WHERE user_id=? AND state IN ('heard', 'imitated', 'recognized', 'understood', 'usable')""",
        (user_id,),
    ).fetchall()
    return {str(row["word"]) for row in rows}


def text_uses_only_allowed_words(text: str, allowed_words: set[str]) -> bool:
    """Return True only when a non-empty transcript uses known lexical items."""
    if not isinstance(text, str):
        return False
    tokens = re.findall(
        r"[\wÀ-ÖØ-öø-ÿ'-]+", text.casefold(), flags=re.UNICODE
    )
    return bool(tokens) and all(token in allowed_words for token in tokens)


def gate_spoken_text(
    text: str,
    usable_words: set[str],
    max_words: int | None = None,
) -> str:
    """Filter lexical output; newborn mode can be restricted to isolated words."""
    if max_words is not None and (
        isinstance(max_words, bool) or not isinstance(max_words, int) or max_words < 1
    ):
        raise ValueError("La limite de mots doit être un entier positif.")
    if not isinstance(text, str) or not usable_words:
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
