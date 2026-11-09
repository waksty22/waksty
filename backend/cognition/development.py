"""Chappie V26 — affect, raisonnement décisionnel et personnalité émergente.

Les émotions sont des états logiciels simulés, jamais présentés comme des
sensations humaines. Les préférences ne sont enregistrées que sur déclaration
explicite ou choix documenté ; aucune préférence n'est inférée d'une réponse LLM.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from cognition.event_receipts import claim_cognitive_event


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, limit: int = 2000) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _confidence(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
        if not math.isfinite(number):
            return default
        return max(0.0, min(1.0, number))
    except (TypeError, ValueError, OverflowError):
        return default


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "{}"


def init_development_tables(db) -> None:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS affective_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            source TEXT NOT NULL,
            event_label TEXT NOT NULL,
            state_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_affective_user_time
            ON affective_history(user_id, id DESC);

        CREATE TABLE IF NOT EXISTS decision_journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            question TEXT NOT NULL,
            options_json TEXT NOT NULL,
            chosen_option TEXT NOT NULL DEFAULT '',
            reasons TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            confidence REAL NOT NULL DEFAULT 0.5,
            outcome TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'considered'
                CHECK(status IN ('considered','chosen','evaluated','revised')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_decisions_user_time
            ON decision_journal(user_id, id DESC);

        CREATE TABLE IF NOT EXISTS preference_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            domain TEXT NOT NULL,
            preference TEXT NOT NULL,
            evidence TEXT NOT NULL,
            basis TEXT NOT NULL CHECK(basis IN ('explicit_statement','documented_choice')),
            confidence REAL NOT NULL DEFAULT 0.7,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, domain, preference, evidence)
        );
        CREATE INDEX IF NOT EXISTS idx_preferences_user_domain
            ON preference_evidence(user_id, domain, id DESC);
    """)


def record_affective_snapshot(
    db, user_id: str, emotions: dict[str, Any],
    source: str = "conversation", event_label: str = "interaction",
    event_id: str | None = None,
) -> dict[str, Any]:
    allowed = ("joy", "fear", "curiosity", "frustration", "sadness", "energy")
    state = {}
    for key in allowed:
        try:
            value = float(emotions.get(key, 0))
            state[key] = round(max(0.0, min(100.0, value)), 2) if math.isfinite(value) else 0.0
        except (TypeError, ValueError, OverflowError):
            state[key] = 0.0
    if event_id and not claim_cognitive_event(
        db, user_id, event_id, "affective_snapshot"
    ):
        return {"duplicate": True, "state": state}

    now = _now()
    cursor = db.execute(
        """INSERT INTO affective_history
        (user_id, source, event_label, state_json, created_at)
        VALUES (?, ?, ?, ?, ?)""",
        (user_id, _text(source, 40) or "unknown",
         _text(event_label, 120) or "interaction", _json(state), now),
    )
    return {"id": cursor.lastrowid, "state": state, "created_at": now}


def list_affective_history(db, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT id, source, event_label, state_json, created_at
        FROM affective_history WHERE user_id=? ORDER BY id DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["state"] = json.loads(item.pop("state_json"))
        except (ValueError, TypeError):
            item["state"] = {}
        result.append(item)
    return result


def record_decision(
    db, user_id: str, question: str, options: list[Any],
    chosen_option: str = "", reasons: str = "",
    evidence: list[Any] | None = None, confidence: Any = 0.5,
) -> dict[str, Any]:
    question = _text(question, 2000)
    if not question:
        raise ValueError("La question de décision est obligatoire.")
    if not isinstance(options, list) or not options:
        raise ValueError("Au moins une option est nécessaire.")
    clean_options = [_text(option, 500) for option in options[:12]]
    clean_options = [option for option in clean_options if option]
    if not clean_options:
        raise ValueError("Les options ne peuvent pas être vides.")
    chosen = _text(chosen_option, 500)
    if chosen and chosen not in clean_options:
        raise ValueError("L'option choisie doit figurer parmi les options proposées.")
    now = _now()
    status = "chosen" if chosen else "considered"
    cursor = db.execute(
        """INSERT INTO decision_journal
        (user_id, question, options_json, chosen_option, reasons,
         evidence_json, confidence, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, question, _json(clean_options), chosen, _text(reasons),
         _json(evidence if isinstance(evidence, list) else []),
         _confidence(confidence), status, now, now),
    )
    return {
        "id": cursor.lastrowid, "question": question, "options": clean_options,
        "chosen_option": chosen, "reasons": _text(reasons),
        "confidence": _confidence(confidence), "status": status,
        "created_at": now,
    }


def evaluate_decision(
    db, user_id: str, decision_id: int, outcome: str,
    revised_choice: str = "",
) -> dict[str, Any]:
    row = db.execute(
        "SELECT * FROM decision_journal WHERE id=? AND user_id=?",
        (int(decision_id), user_id),
    ).fetchone()
    if row is None:
        raise ValueError("Décision introuvable.")
    outcome = _text(outcome, 3000)
    if not outcome:
        raise ValueError("Le résultat observé est obligatoire.")
    choice = _text(revised_choice, 500) or row["chosen_option"]
    if choice:
        try:
            options = json.loads(row["options_json"])
        except (ValueError, TypeError):
            options = []
        if choice not in options:
            raise ValueError("Le choix révisé doit figurer parmi les options.")
    status = "revised" if revised_choice else "evaluated"
    now = _now()
    db.execute(
        """UPDATE decision_journal SET outcome=?, chosen_option=?,
        status=?, updated_at=? WHERE id=? AND user_id=?""",
        (outcome, choice, status, now, int(decision_id), user_id),
    )
    return {"id": int(decision_id), "outcome": outcome,
            "chosen_option": choice, "status": status, "updated_at": now}


def list_decisions(db, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT * FROM decision_journal WHERE user_id=?
        ORDER BY id DESC LIMIT ?""", (user_id, limit)
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for field, target in (("options_json", "options"), ("evidence_json", "evidence")):
            try:
                item[target] = json.loads(item.pop(field))
            except (ValueError, TypeError):
                item[target] = []
        result.append(item)
    return result


def record_preference(
    db, user_id: str, domain: str, preference: str,
    evidence: str, basis: str = "explicit_statement",
    confidence: Any = 0.8,
) -> dict[str, Any]:
    domain = _text(domain, 100)
    preference = _text(preference, 500)
    evidence = _text(evidence, 2000)
    if not domain or not preference or not evidence:
        raise ValueError("Domaine, préférence et preuve sont obligatoires.")
    if basis not in {"explicit_statement", "documented_choice"}:
        raise ValueError("La préférence doit provenir d'une déclaration ou d'un choix documenté.")
    now = _now()
    db.execute(
        """INSERT OR IGNORE INTO preference_evidence
        (user_id, domain, preference, evidence, basis, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (user_id, domain, preference, evidence, basis, _confidence(confidence), now),
    )
    row = db.execute(
        """SELECT id, domain, preference, evidence, basis, confidence, created_at
        FROM preference_evidence
        WHERE user_id=? AND domain=? AND preference=? AND evidence=?""",
        (user_id, domain, preference, evidence),
    ).fetchone()
    return dict(row)


def list_preferences(db, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    rows = db.execute(
        """SELECT id, domain, preference, evidence, basis, confidence, created_at
        FROM preference_evidence WHERE user_id=?
        ORDER BY domain ASC, id DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def development_statistics(db, user_id: str) -> dict[str, int]:
    def count(table: str) -> int:
        return int(db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user_id,)
        ).fetchone()[0])
    return {
        "affective_snapshots": count("affective_history"),
        "decisions": count("decision_journal"),
        "documented_preferences": count("preference_evidence"),
    }
