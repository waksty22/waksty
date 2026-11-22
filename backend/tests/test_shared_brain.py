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


class _TransactionCheckingConnection:
    def __init__(self, connection):
        self.connection = connection

    @property
    def in_transaction(self):
        return self.connection.in_transaction

    def execute(self, sql, parameters=()):
        if sql.lstrip().upper().startswith("SELECT"):
            assert self.connection.in_transaction, (
                "every snapshot SELECT must share an explicit read transaction"
            )
        return self.connection.execute(sql, parameters)

    def commit(self):
        return self.connection.commit()

    def rollback(self):
        return self.connection.rollback()


def test_snapshot_reads_are_consistent_and_caller_transactions_are_preserved():
    db = make_db()
    checked = _TransactionCheckingConnection(db)

    # A standalone snapshot must open and release its own read transaction.
    get_shared_brain_snapshot(checked, "creator")
    assert not db.in_transaction

    # When called inside a caller-owned transaction, the snapshot must not
    # commit or end the caller's transaction.
    db.execute(
        "INSERT INTO personal_vocabulary VALUES "
        "(1,'creator','bonjour','','heard',1,'','t0','t1')"
    )
    assert db.in_transaction
    snapshot = get_shared_brain_snapshot(checked, "creator")
    assert snapshot["vocabulary"][0]["word"] == "bonjour"
    assert db.in_transaction
    db.rollback()
    db.close()


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


def test_snapshot_surfaces_schema_errors_instead_of_silently_hiding_data():
    db = make_db()
    db.execute("DROP TABLE personal_vocabulary")
    db.execute(
        "CREATE TABLE personal_vocabulary "
        "(user_id TEXT, word TEXT, state TEXT)"
    )

    try:
        get_shared_brain_snapshot(db, "creator")
    except sqlite3.OperationalError as exc:
        assert "no such column" in str(exc).casefold()
    else:
        raise AssertionError("A broken existing table must not look like empty vocabulary")
    db.close()


def test_memories_v19_schema_error_does_not_fall_back_to_legacy_memories():
    db = make_db()
    db.execute(
        "CREATE TABLE memories_v19 (id INTEGER, user_id TEXT, category TEXT, content TEXT)"
    )

    try:
        get_shared_brain_snapshot(db, "creator")
    except sqlite3.OperationalError as exc:
        assert "no such column" in str(exc).casefold()
    else:
        raise AssertionError("A broken V19 memory table must not be hidden by legacy fallback")
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
    assert merge_live_transcript("Bonjour Chappie", "encore") == "Bonjour Chappie encore"
    assert merge_live_transcript("hello", "lo world") == "hello lo world"


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
        r"ÉPISODES AUTOBIOGRAPHIQUES SOURCÉS:\n(\[.*?\])",
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
        r"VOCABULAIRE PERSONNEL — état d'acquisition:\n(\[.*?\])",
        context,
        flags=re.S,
    )
    assert match is not None
    assert json.loads(match.group(1)) == snapshot["vocabulary"]
    assert "STATISTIQUES DES DONNÉES PERSISTÉES" in context
    assert "CONTEXTE PARTIEL" not in context



def test_snapshot_rejects_coerced_limits_and_invalid_user_ids():
    db = make_db()
    for invalid_limit in (True, False, 1.5, "5", None, 0, -1):
        try:
            get_shared_brain_snapshot(db, "creator", limit=invalid_limit)
        except ValueError:
            pass
        else:
            raise AssertionError(f"limit should be rejected: {invalid_limit!r}")

    for invalid_user in ("", "   ", "x" * 81, 123, None):
        try:
            get_shared_brain_snapshot(db, invalid_user)
        except ValueError:
            pass
        else:
            raise AssertionError(f"user_id should be rejected: {invalid_user!r}")

    snapshot = get_shared_brain_snapshot(db, " creator ", limit=2)
    assert snapshot["statistics"]["totals"]["vocabulary"] == 0
    db.close()



def test_shared_brain_excludes_corrupt_legacy_memory_records():
    db = make_db()
    db.execute(
        "INSERT INTO memories VALUES (1,'creator','general','Souvenir valide',3,?,0,'t0','t1')",
        (json.dumps(["ok"]),),
    )
    db.execute(
        "INSERT INTO memories VALUES (2,'creator','general',?,3,'[]',0,'t0','t1')",
        (b"contenu binaire",),
    )
    db.execute(
        "INSERT INTO memories VALUES (3,'creator','general','Tags binaires',3,?,0,'t0','t1')",
        (b"tags binaires",),
    )
    snapshot = get_shared_brain_snapshot(db, "creator")
    assert [row["content"] for row in snapshot["memories"]] == ["Souvenir valide"]
    assert snapshot["memories"][0]["tags"] == ["ok"]
    db.close()



def test_shared_brain_rejects_unknown_memory_provenance():
    db = make_db()
    db.execute(
        "INSERT INTO memories VALUES (1,'creator','general','Souvenir sans provenance fiable',3,?,0,'t0','t1')",
        (json.dumps([]),),
    )
    # Add the newer provenance column to simulate the V19 schema.
    db.execute("ALTER TABLE memories ADD COLUMN source_type TEXT")
    db.execute("UPDATE memories SET source_type='fabricated'")
    db.execute(
        "INSERT INTO memories VALUES (2,'creator','general','Provenance binaire',3,?,0,'t0','t1',?)",
        (json.dumps([]), b"taught"),
    )
    snapshot = get_shared_brain_snapshot(db, "creator")
    assert snapshot["memories"] == []
    db.close()



def test_live_transcript_ignores_repeated_shorter_prefix_chunks():
    assert merge_live_transcript(
        "Bonjour tout le monde", "Bonjour tout"
    ) == "Bonjour tout le monde"
    assert merge_live_transcript(
        "Bonjour tout le monde", "bonjour TOUT"
    ) == "Bonjour tout le monde"

def test_live_transcript_rejects_non_text_chunks_without_stringifying_them():
    for invalid in (None, 123, 1.5, True, b"Bonjour", {"text": "Bonjour"}, ["Bonjour"]):
        assert merge_live_transcript("Bonjour", invalid) == "Bonjour"
        assert merge_live_transcript(invalid, "salut") == "salut"


def test_snapshot_includes_validated_word_links_and_unconfirmed_perception_candidates():
    db = make_db()
    db.executescript("""
        CREATE TABLE word_visual_associations (
            id INTEGER PRIMARY KEY, user_id TEXT, word TEXT,
            observation_id TEXT, evidence TEXT, created_at TEXT
        );
        CREATE TABLE perception_fusion_candidates (
            id INTEGER PRIMARY KEY, user_id TEXT,
            audio_observation_id TEXT, vision_observation_id TEXT,
            time_delta_seconds REAL, status TEXT, evidence_json TEXT,
            created_at TEXT
        );
    """)
    db.execute(
        "INSERT INTO word_visual_associations VALUES (1,'creator','pomme','vision-1','validation explicite','t2')"
    )
    db.execute(
        "INSERT INTO perception_fusion_candidates VALUES (1,'creator','audio-1','vision-1',1.2,'candidate',?, 't3')",
        (json.dumps({"rule": "temporal_cooccurrence_only"}),),
    )

    snapshot = get_shared_brain_snapshot(db, "creator")
    assert snapshot["word_visual_associations"][0]["word"] == "pomme"
    assert snapshot["perception_fusions"][0]["status"] == "candidate"
    assert snapshot["perception_fusions"][0]["evidence"]["rule"] == "temporal_cooccurrence_only"

    context = format_shared_brain_context(snapshot)
    assert "ASSOCIATIONS MOT-IMAGE" in context
    assert "RAPPROCHEMENTS AUDIO/VISION" in context
    assert "coïncidences temporelles, non confirmées" in context
    db.close()


def test_live_shared_brain_tool_reads_latest_persisted_snapshot_each_call(monkeypatch):
    from contextlib import nullcontext
    import server

    db = make_db()
    monkeypatch.setattr(server, "db_connection", lambda: nullcontext(db))

    db.execute(
        "INSERT INTO personal_vocabulary VALUES "
        "(1,'creator','bonjour','','heard',1,'audio','t0','t1')"
    )
    first = server.execute_tool("get_shared_brain_state", {}, "creator")
    assert [item["word"] for item in first["vocabulary"]] == ["bonjour"]

    # Simulate a new learning event committed while the same Live session stays open.
    db.execute(
        "INSERT INTO personal_vocabulary VALUES "
        "(2,'creator','merci','','heard',1,'audio','t1','t2')"
    )
    db.commit()

    second = server.execute_tool("get_shared_brain_state", {}, "creator")
    assert {item["word"] for item in second["vocabulary"]} == {"bonjour", "merci"}
    assert second["statistics"]["totals"]["vocabulary"] == 2
    db.close()


def test_live_system_policy_requires_refresh_before_relying_on_session_snapshot():
    from server import IDENTITY_SYSTEM_INSTRUCTION

    policy = IDENTITY_SYSTEM_INSTRUCTION.casefold()
    assert "instantané qui peut devenir obsolète" in policy
    assert "appelle l'outil get_shared_brain_state avant de répondre" in policy
    assert "n'affirme jamais un apprentissage absent de cet état" in policy
    declarations = server_tool_declarations()
    refresh_tool = next(
        tool for tool in declarations
        if tool.get("name") == "get_shared_brain_state"
    )
    assert "OBLIGATOIRE avant toute réponse" in refresh_tool["description"]


def server_tool_declarations():
    import server

    return server.TOOLS[0]["functionDeclarations"]
