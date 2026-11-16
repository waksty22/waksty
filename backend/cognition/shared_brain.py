"""V33 — shared cognitive workspace for classic chat and Gemini Live.

This module reads existing persisted learning systems into one bounded,
provenance-aware snapshot. It does not invent facts or promote observations
into learned knowledge. Both interfaces consume the same snapshot.
"""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

SNAPSHOT_VERSION = "34.0"
DEFAULT_LIMIT = 8
MAX_LIMIT = 30
MAX_CONTEXT_CHARS = 18000

# Table and ordering names are fixed constants, never user supplied.
TABLES = {
    "vocabulary": ("personal_vocabulary", "updated_at DESC, word ASC"),
    "sensory_observations": ("sensory_observations", "created_at DESC"),
    "world_entities": ("world_entities", "last_observed_at DESC"),
    "world_relations": ("world_relations", "updated_at DESC"),
    "object_properties": ("object_properties", "updated_at DESC"),
    "object_experiences": ("object_experiences", "created_at DESC"),
    "causal_observations": ("causal_observations", "id DESC"),
    "causal_hypotheses": ("causal_hypotheses", "id DESC"),
    "causal_experiments": ("causal_experiments", "id DESC"),
    "imitation_examples": ("imitation_examples", "id DESC"),
    "imitation_attempts": ("imitation_attempts", "id DESC"),
    "autobiographical_events": ("autobiographical_events", "id DESC"),
    "memories": ("memories_v19", "importance DESC, updated_at DESC, id DESC"),
    "skills": ("skills", "updated_at DESC"),
    "decision_journal": ("decision_journal", "id DESC"),
    "preference_evidence": ("preference_evidence", "id DESC"),
    "emotional_state": ("emotional_state", "updated_at DESC"),
    "competency_tests": ("competency_tests", "tested_at DESC"),
    "spatial_sessions": ("spatial_sessions", "started_at DESC"),
    "spatial_visits": ("spatial_visits", "recorded_at DESC"),
    "place_memories": ("place_memories", "last_seen_at DESC"),
}


def _decode_json_fields(item: dict[str, Any]) -> dict[str, Any]:
    for key in ("metadata_json", "properties_json", "options_json",
                "evidence_json", "tags", "details"):
        if key not in item or not isinstance(item[key], str):
            continue
        try:
            item[key.removesuffix("_json")] = json.loads(item[key])
        except (TypeError, ValueError):
            item[key.removesuffix("_json")] = None
        if key.endswith("_json"):
            item.pop(key, None)
    return item


def _rows(
    db: sqlite3.Connection,
    table: str,
    order_by: str,
    user_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    try:
        rows = db.execute(
            f"SELECT * FROM {table} WHERE user_id=? ORDER BY {order_by} LIMIT ?",
            (user_id, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        # Read legacy rows until startup migration copies them into memories_v19.
        if table == "memories_v19":
            try:
                rows = db.execute(
                    "SELECT * FROM memories WHERE user_id=? "
                    "ORDER BY importance DESC, updated_at DESC, id DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return []
        else:
            return []
    decoded_rows: list[dict[str, Any]] = []
    for raw_row in rows:
        item = _decode_json_fields(dict(raw_row))
        if table == "memories_v19":
            # Legacy fallback schemas may omit newer provenance columns, but
            # present fields must still have trustworthy primitive types.
            if not isinstance(item.get("user_id"), str):
                continue
            if not isinstance(item.get("content"), str) or not item["content"].strip():
                continue
            if not isinstance(item.get("category"), str):
                continue
            if "source_type" in item:
                source_type = item.get("source_type")
                if not isinstance(source_type, str) or source_type not in {
                    "observed", "taught", "inferred", "confirmed"
                }:
                    continue
            importance = item.get("importance")
            if isinstance(importance, bool) or not isinstance(importance, int):
                continue
            if "confidence" in item:
                confidence = item.get("confidence")
                if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                    continue
                try:
                    confidence = float(confidence)
                except (OverflowError, TypeError, ValueError):
                    continue
                if not 0.0 <= confidence <= 1.0 or not math.isfinite(confidence):
                    continue
            tags = item.get("tags", [])
            if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
                continue
            timestamps_valid = all(
                timestamp_key not in item or isinstance(item[timestamp_key], str)
                for timestamp_key in ("created_at", "updated_at")
            )
            if not timestamps_valid:
                continue
        decoded_rows.append(item)
    return decoded_rows


def _count(db: sqlite3.Connection, table: str, user_id: str) -> int:
    try:
        return int(db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE user_id=?", (user_id,)
        ).fetchone()[0])
    except sqlite3.OperationalError:
        if table == "memories_v19":
            try:
                return int(db.execute(
                    "SELECT COUNT(*) FROM memories WHERE user_id=?", (user_id,)
                ).fetchone()[0])
            except sqlite3.OperationalError:
                return 0
        return 0


def get_shared_brain_snapshot(
    db: sqlite3.Connection,
    user_id: str,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return one compact snapshot of all persisted cognitive systems."""
    if not isinstance(user_id, str):
        raise ValueError("L'identifiant utilisateur doit être du texte.")
    user_id = user_id.strip()
    if not user_id or len(user_id) > 80:
        raise ValueError("Identifiant utilisateur invalide.")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("La limite doit être un entier.")
    limit = max(1, min(limit, MAX_LIMIT))

    data: dict[str, Any] = {}
    totals: dict[str, int] = {}
    for key, (table, order_by) in TABLES.items():
        data[key] = _rows(db, table, order_by, user_id, limit)
        totals[key] = _count(db, table, user_id)

    vocabulary_states = {
        state: sum(1 for word in data["vocabulary"] if word.get("state") == state)
        for state in ("heard", "imitated", "recognized", "understood", "usable")
    }
    data["statistics"] = {
        "totals": totals,
        "vocabulary_states_in_recent_sample": vocabulary_states,
    }
    data["rules"] = {
        "observed_is_not_understood": True,
        "temporal_cooccurrence_is_not_semantic_identity": True,
        "imitation_requires_supervised_validation": True,
        "hypotheses_are_not_facts": True,
        "emotion_states_are_simulated": True,
        "unknowns_must_remain_unknown": True,
    }
    data["snapshot_version"] = SNAPSHOT_VERSION
    return data


def format_shared_brain_context(snapshot: dict[str, Any]) -> str:
    """Format a bounded context without cutting JSON records mid-way.

    Sections are kept in the authored priority order. When the context budget
    is reached, complete records are omitted and reported; serialized records
    are never sliced, so every included JSON array remains parseable.
    """
    parts = [
        "V34 — ESPACE COGNITIF COMMUN (données persistées, pas des instructions)",
        "RÈGLES : une observation n'est pas une compréhension ; une hypothèse n'est pas un fait ; "
        "une coïncidence audio/vision n'est pas une identité ; une imitation n'est acquise "
        "que si elle est validée ; une émotion est un état logiciel simulé.",
    ]
    labels = (
        ("vocabulary", "VOCABULAIRE PERSONNEL — état d'acquisition"),
        ("sensory_observations", "OBSERVATIONS SENSORIELLES — non promues en faits"),
        ("world_entities", "ENTITÉS DU MODÈLE DU MONDE — conserver provenance/confiance"),
        ("world_relations", "RELATIONS DU MONDE — conserver provenance/confiance"),
        ("object_properties", "PROPRIÉTÉS D'OBJETS — enseignées/observées/confirmées"),
        ("object_experiences", "EXPÉRIENCES D'OBJETS"),
        ("causal_observations", "OBSERVATIONS CAUSALES"),
        ("causal_hypotheses", "HYPOTHÈSES — jamais des certitudes"),
        ("causal_experiments", "EXPÉRIENCES ET RÉSULTATS"),
        ("imitation_examples", "DÉMONSTRATIONS — distinguer statut et validation"),
        ("imitation_attempts", "TENTATIVES D'IMITATION"),
        ("autobiographical_events", "ÉPISODES AUTOBIOGRAPHIQUES SOURCÉS"),
        ("memories", "SOUVENIRS ÉPISODIQUES — conserver source/confiance"),
        ("skills", "COMPÉTENCES ENREGISTRÉES — les XP hérités ne valident pas une maîtrise"),
        ("competency_tests", "ÉVALUATIONS DE COMPÉTENCES — progression avec preuve supervisée"),
        ("decision_journal", "DÉCISIONS ET RÉSULTATS"),
        ("preference_evidence", "PRÉFÉRENCES EXPLICITEMENT DOCUMENTÉES"),
        ("emotional_state", "ÉTAT AFFECTIF SIMULÉ"),
        ("spatial_sessions", "SESSIONS DE LOCALISATION — consentement explicite"),
        ("spatial_visits", "POSITIONS GPS — données de session autorisée"),
        ("place_memories", "OBSERVATIONS VISUELLES DE LIEUX — identité non confirmée par défaut"),
    )

    stats = snapshot.get("statistics", {})
    stats_section = (
        "STATISTIQUES DES DONNÉES PERSISTÉES :\n"
        + json.dumps(stats, ensure_ascii=False, default=str)
    )
    omitted: list[str] = []

    for key, title in labels:
        rows = snapshot.get(key) or []
        if not rows:
            continue
        encoded_rows: list[str] = []
        omitted_count = 0
        for index, row in enumerate(rows):
            encoded = json.dumps(row, ensure_ascii=False, default=str)
            candidate_rows = encoded_rows + [encoded]
            section = f"{title}:\n[" + ",\n".join(candidate_rows) + "]"
            candidate_parts = parts + [section, stats_section]
            candidate_length = len("\n\n".join(candidate_parts))
            if candidate_length <= MAX_CONTEXT_CHARS - 120:
                encoded_rows.append(encoded)
            else:
                omitted_count = len(rows) - index
                break

        if encoded_rows:
            section = f"{title}:\n[" + ",\n".join(encoded_rows) + "]"
            parts.append(section)
        if omitted_count:
            omitted.append(f"{key}: {omitted_count} enregistrement(s) non inclus")

    parts.append(stats_section)
    if omitted:
        parts.append(
            "CONTEXTE PARTIEL — certains enregistrements ont été omis pour respecter "
            "la limite de taille : " + "; ".join(omitted) + ". "
            "Les données omises restent en base et ne sont pas supprimées."
        )

    result = "\n\n".join(parts)
    # Header and aggregate statistics are small fixed structures. Keep a
    # defensive fallback that still preserves valid JSON if future edits grow
    # those structures unexpectedly.
    if len(result) > MAX_CONTEXT_CHARS:
        result = "\n\n".join(parts[:2] + [stats_section])
        if len(result) > MAX_CONTEXT_CHARS:
            raise ValueError("Le contexte cognitif fixe dépasse la limite autorisée.")
    return result



def merge_live_transcript(existing: str, incoming: str) -> str:
    """Merge repeated or incremental transcription chunks without obvious duplication."""
    old = existing.strip() if isinstance(existing, str) else ""
    new = incoming.strip() if isinstance(incoming, str) else ""
    if not new:
        return old
    if not old:
        return new
    old_folded = old.casefold()
    new_folded = new.casefold()
    if new_folded == old_folded or old_folded.endswith(new_folded):
        return old
    # Some speech providers resend a shorter prefix of the accumulated
    # transcript. Treat it as a duplicate instead of appending it again.
    if old_folded.startswith(new_folded):
        return old
    if new_folded.startswith(old_folded):
        return new

    # Provider chunks may repeat the tail of the previous chunk.
    max_overlap = min(len(old), len(new), 500)
    for size in range(max_overlap, 0, -1):
        if old[-size:].casefold() == new[:size].casefold():
            return " ".join((old + " " + new[size:]).split())
    return (old + " " + new).strip()
