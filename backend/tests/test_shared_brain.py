import sqlite3
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition.shared_brain import (
    format_shared_brain_context,
    get_shared_brain_snapshot,
    merge_live_transcript,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE personal_vocabulary (
            id INTEGER PRIMARY KEY, user_id TEXT, word TEXT, meaning TEXT,
            state TEXT, exposure_count INTEGER, evidence TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE sensory_observations (
            observation_id TEXT, user_id TEXT, modality TEXT, content TEXT,
            source TEXT, confidence REAL, metadata_json TEXT, created_at TEXT
        );
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY, user_id TEXT, category TEXT, content TEXT,
            importance INTEGER, tags TEXT, access_count INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE skills (
            id INTEGER PRIMARY KEY, user_id TEXT, skill_name TEXT, level REAL,
            xp REAL, evidence TEXT, updated_at TEXT
        );
        CREATE TABLE emotional_state (
            user_id TEXT, joy REAL, fear REAL, curiosity REAL,
            frustration REAL, sadness REAL, energy REAL, updated_at TEXT
        );
    """)
    return db


def test_snapshot_unifies_persisted_modules_without_promoting_observations():
    db = make_db()
    db.execute(
        "INSERT INTO personal_vocabulary VALUES (1,'creator','pomme','fruit','heard',1,'heard once','t0','t1')"
    )
    db.execute(
        "INSERT INTO sensory_observations VALUES ('obs1','creator','vision','forme rouge','camera',0.4,'{}','t1')"
    )
    db.execute(
        "INSERT INTO memories VALUES (1,'creator','general','fait enseigné',4,'[]',0,'t0','t1')"
    )
    snapshot = get_shared_brain_snapshot(db, "creator")
    assert snapshot["vocabulary"][0]["state"] == "heard"
    assert snapshot["sensory_observations"][0]["modality"] == "vision"
    assert snapshot["memories"][0]["content"] == "fait enseigné"
    assert snapshot["rules"]["observed_is_not_understood"] is True
    assert snapshot["statistics"]["totals"]["vocabulary"] == 1
    db.close()


def test_snapshot_is_scoped_to_user():
    db = make_db()
    db.execute(
        "INSERT INTO personal_vocabulary VALUES (1,'alice','bonjour','','heard',1,'','t0','t1')"
    )
    snapshot = get_shared_brain_snapshot(db, "bob")
    assert snapshot["vocabulary"] == []
    assert snapshot["statistics"]["totals"]["vocabulary"] == 0
    db.close()


def test_context_format_is_bounded_and_explicit():
    db = make_db()
    snapshot = get_shared_brain_snapshot(db, "creator")
    context = format_shared_brain_context(snapshot)
    assert "V34" in context
    assert "une hypothèse n'est pas un fait" in context
    assert len(context) <= 19000
    db.close()


def test_live_transcript_merges_incremental_chunks():
    assert merge_live_transcript("", "Bonjour") == "Bonjour"
    assert merge_live_transcript("Bonjour", "Bonjour") == "Bonjour"
    assert merge_live_transcript("Bonjour tout", "tout va bien") == "Bonjour tout va bien"
    assert merge_live_transcript("Bonjour", "Bonjour tout le monde") == "Bonjour tout le monde"


def test_context_budget_never_cuts_json_records_and_reports_omissions():
    from cognition.shared_brain import MAX_CONTEXT_CHARS

    rows = [
        {"id": index, "content": "souvenir " + ("important " * 90)}
        for index in range(120)
    ]
    snapshot = {
        "autobiographical_events": rows,
        "statistics": {"totals": {"autobiographical_events": len(rows)}},
        "rules": {"unknowns_must_remain_unknown": True},
    }
    context = format_shared_brain_context(snapshot)

    assert len(context) <= MAX_CONTEXT_CHARS
    assert "CONTEXTE PARTIEL" in context
    assert "Les données omises restent en base" in context

    match = re.search(
        r"ÉPISODES AUTOBIOGRAPHIQUES SOURCÉS:\\n(\\[.*?\\])",
        context,
        flags=re.S,
    )
    assert match is not None
    decoded = json.loads(match.group(1))
    assert decoded
    assert all(isinstance(item, dict) and "id" in item for item in decoded)
    assert decoded[-1]["id"] < len(rows) - 1


def test_context_keeps_statistics_and_all_records_when_under_budget():
    snapshot = {
        "vocabulary": [{"word": "bonjour", "state": "heard"}],
        "statistics": {"totals": {"vocabulary": 1}},
    }
    context = format_shared_brain_context(snapshot)
    match = re.search(
        r"VOCABULAIRE PERSONNEL — état d'acquisition:\\n(\\[.*?\\])",
        context,
        flags=re.S,
    )
    assert match is not None
    assert json.loads(match.group(1)) == snapshot["vocabulary"]
    assert "STATISTIQUES DES DONNÉES PERSISTÉES" in context
    assert "CONTEXTE PARTIEL" not in context
