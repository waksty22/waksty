"""Full Chappie application-schema logical backup/restore regression test.

Builds a disposable SQLite database using the real application init_db path,
seeds representative memory/learning/world/relationship data, then verifies
an encrypted archive can reconstruct the complete schema and every row in a
second isolated SQLite database. No Render or Turso credentials are used.
"""
from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

from scripts.backup_turso import create_backup_archive
from storage.logical_backup import restore_encrypted_logical_backup
from storage.schema_audit import compare_schemas, inspect_schema


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _user_tables(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]


def _seed_chappie_state(db: sqlite3.Connection) -> None:
    """Seed representative durable state across core, learning and world data."""
    db.execute(
        "INSERT INTO conversations(user_id,role,content,created_at) VALUES(?,?,?,?)",
        ("creator", "user", "Je m'appelle Créateur.", "2026-11-14T10:00:00Z"),
    )
    db.execute(
        """INSERT INTO memories
           (user_id,category,content,importance,tags,access_count,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("creator", "identity", "Le créateur s'appelle Créateur.", 5, '["identity"]', 2,
         "2026-11-14T10:00:00Z", "2026-11-14T10:00:00Z"),
    )
    db.execute(
        """INSERT INTO memories_v19
           (user_id,category,content,importance,source_type,confidence,tags,
            access_count,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        ("creator", "object", "Un objet a été observé.", 4, "observed", 0.9,
         '["test"]', 1, "2026-11-14T10:01:00Z", "2026-11-14T10:01:00Z"),
    )
    db.execute(
        """INSERT INTO emotional_state
           (user_id,joy,fear,curiosity,frustration,sadness,energy,updated_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("creator", 40, 10, 75, 2, 3, 95, "2026-11-14T10:02:00Z"),
    )
    db.execute(
        "INSERT INTO relationships(user_id,trust,affection,dependence,updated_at) VALUES(?,?,?,?,?)",
        ("creator", 95, 90, 5, "2026-11-14T10:02:00Z"),
    )
    db.execute(
        "INSERT INTO dreams(user_id,content,created_at) VALUES(?,?,?)",
        ("creator", "Un rêve de test conservé.", "2026-11-14T10:03:00Z"),
    )
    db.execute(
        """INSERT INTO skills(user_id,skill_name,level,xp,evidence,updated_at)
           VALUES(?,?,?,?,?,?)""",
        ("creator", "observation", 3.5, 40, "test supervisé", "2026-11-14T10:04:00Z"),
    )
    goal = db.execute(
        """INSERT INTO goals(user_id,title,status,progress,created_at,updated_at)
           VALUES(?,?,?,?,?,?)""",
        ("creator", "Comprendre les objets", "active", 0.25,
         "2026-11-14T10:05:00Z", "2026-11-14T10:05:00Z"),
    ).lastrowid
    db.execute(
        """INSERT INTO goal_steps(goal_id,description,status,evidence,updated_at)
           VALUES(?,?,?,?,?)""",
        (goal, "Observer un objet", "completed", "Observation enregistrée",
         "2026-11-14T10:06:00Z"),
    )
    db.execute(
        """INSERT INTO world_entities
           (id,user_id,entity_type,properties_json,source_type,confidence,last_observed_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("entity-a", "creator", "object", '{"label":"ballon"}', "observed", 0.9,
         "2026-11-14T10:07:00Z"),
    )
    db.execute(
        """INSERT INTO world_entities
           (id,user_id,entity_type,properties_json,source_type,confidence,last_observed_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("entity-b", "creator", "place", '{"label":"terrain"}', "observed", 0.8,
         "2026-11-14T10:07:00Z"),
    )
    db.execute(
        """INSERT INTO world_relations
           (user_id,subject_id,predicate,object_id,source_type,confidence,updated_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("creator", "entity-a", "observed_at", "entity-b", "observed", 0.8,
         "2026-11-14T10:08:00Z"),
    )
    db.execute(
        """INSERT INTO personal_vocabulary
           (user_id,word,meaning,state,exposure_count,evidence,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("creator", "ballon", "objet rond", "heard", 2, "mot entendu",
         "2026-11-14T10:09:00Z", "2026-11-14T10:09:00Z"),
    )
    observation = db.execute(
        """INSERT INTO causal_observations
           (user_id,event,context,outcome,source_type,evidence,confidence,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("creator", "Le ballon tombe", "simulation", "Il touche le sol", "observed",
         "observation de test", 0.8, "2026-11-14T10:10:00Z"),
    ).lastrowid
    hypothesis = db.execute(
        """INSERT INTO causal_hypotheses
           (user_id,observation_id,statement,predicted_effect,confidence,status,
            evidence_count,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        ("creator", observation, "La gravité attire le ballon", "Le ballon descend",
         0.6, "proposed", 0, "2026-11-14T10:11:00Z", "2026-11-14T10:11:00Z"),
    ).lastrowid
    db.execute(
        """INSERT INTO causal_experiments
           (user_id,hypothesis_id,environment,procedure,prediction,
            supervisor_approved,status,result,evaluation,created_at)
           VALUES(?,?,?,?,?,1,'planned','','',"2026-11-14T10:12:00Z")""",
        ("creator", hypothesis, "simulation", "Lâcher un objet", "Il descend"),
    )
    db.execute(
        """INSERT INTO competency_tests
           (user_id,test_name,passed,score,details,tested_at)
           VALUES(?,?,?,?,?,?)""",
        ("creator", "observation:object", 1, 85, '{"evidence":"test"}',
         "2026-11-14T10:13:00Z"),
    )
    # Conversation summaries, intentions and free-form thoughts.
    db.execute(
        "INSERT INTO conversations(user_id,role,content,created_at) VALUES(?,?,?,?)",
        ("creator", "assistant", "Je me souviens de cette conversation.", "2026-11-14T10:14:00Z"),
    )
    conversation_ids = [
        row[0] for row in db.execute(
            "SELECT id FROM conversations WHERE user_id='creator' ORDER BY id"
        ).fetchall()
    ]
    db.execute(
        """INSERT INTO conversation_summaries
           (user_id,summary,through_conversation_id,created_at)
           VALUES(?,?,?,?)""",
        ("creator", "Résumé de test conservé.", conversation_ids[-1],
         "2026-11-14T10:15:00Z"),
    )
    db.execute(
        """INSERT INTO user_intentions
           (user_id,current_intent,confidence,details,updated_at)
           VALUES(?,?,?,?,?)""",
        ("creator", "apprendre", 0.9, '{"source":"test"}', "2026-11-14T10:15:00Z"),
    )
    db.execute(
        "INSERT INTO thoughts(user_id,content,created_at) VALUES(?,?,?)",
        ("creator", "Pensée persistante de test.", "2026-11-14T10:15:00Z"),
    )

    # Autobiographical episodes and their explicit link to source conversations.
    event_ids = []
    for conversation_id, actor, content in (
        (conversation_ids[0], "user", "Le créateur enseigne un mot."),
        (conversation_ids[1], "assistant", "Chappie répète le mot."),
    ):
        cur = db.execute(
            """INSERT INTO autobiographical_events
               (user_id,source_conversation_id,actor,event_type,content,
                happened_at,importance,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            ("creator", conversation_id, actor, "dialogue", content,
             "2026-11-14T10:16:00Z", 3, "2026-11-14T10:16:00Z"),
        )
        event_ids.append(cur.lastrowid)
    db.execute(
        """INSERT INTO autobiographical_links
           (user_id,source_event_id,target_event_id,relation_type,created_at)
           VALUES(?,?,?,?,?)""",
        ("creator", event_ids[0], event_ids[1], "same_dialogue_turn",
         "2026-11-14T10:16:00Z"),
    )

    # Consent-based spatial memory: session, location sample and place record.
    db.execute(
        """INSERT INTO spatial_sessions
           (session_id,user_id,device_label,consented,started_at,ended_at,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("session-test", "creator", "test-device", 1,
         "2026-11-14T10:17:00Z", None, "2026-11-14T10:17:00Z"),
    )
    db.execute(
        """INSERT INTO spatial_visits
           (user_id,session_id,latitude,longitude,accuracy_m,recorded_at,source,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("creator", "session-test", 48.3, -2.7, 10.0,
         "2026-11-14T10:18:00Z", "browser_geolocation", "2026-11-14T10:18:00Z"),
    )
    db.execute(
        """INSERT INTO place_memories
           (place_id,user_id,label,description,visual_signature,session_id,
            latitude,longitude,confidence,identity_status,first_seen_at,
            last_seen_at,observations_count,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("place-test", "creator", "Lieu test", "Un lieu de test.",
         "signature-test", "session-test", 48.3, -2.7, 0.6, "candidate",
         "2026-11-14T10:18:00Z", "2026-11-14T10:18:00Z", 1,
         "2026-11-14T10:18:00Z", "2026-11-14T10:18:00Z"),
    )

    # Audio/vision observations, association and cautious cross-modal candidate.
    for observation_id, modality, content in (
        ("audio-test", "audio", "Un son de ballon."),
        ("vision-test", "vision", "Un ballon rond."),
    ):
        db.execute(
            """INSERT INTO sensory_observations
               (observation_id,user_id,modality,content,source,confidence,
                metadata_json,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (observation_id, "creator", modality, content, "test", 0.9, '{}',
             "2026-11-14T10:19:00Z"),
        )
    db.execute(
        """INSERT INTO word_visual_associations
           (user_id,word,observation_id,evidence,created_at)
           VALUES(?,?,?,?,?)""",
        ("creator", "ballon", "vision-test", "Association visuelle de test.",
         "2026-11-14T10:19:00Z"),
    )
    db.execute(
        """INSERT INTO perception_fusion_candidates
           (user_id,audio_observation_id,vision_observation_id,
            time_delta_seconds,status,evidence_json,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("creator", "audio-test", "vision-test", 1.5, "candidate",
         '{"reason":"temporal_cooccurrence"}', "2026-11-14T10:19:00Z"),
    )

    # Object properties/experiences are tied to a known world entity.
    db.execute(
        """INSERT INTO object_properties
           (user_id,object_id,property_key,property_value,source_type,
            confidence,evidence,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        ("creator", "entity-a", "couleur", "orange", "taught", 0.95,
         "Le créateur l'a enseigné.", "2026-11-14T10:20:00Z",
         "2026-11-14T10:20:00Z"),
    )
    db.execute(
        """INSERT INTO object_experiences
           (user_id,object_id,action,outcome,evidence,source_type,
            confidence,created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        ("creator", "entity-a", "rouler", "Le ballon avance.",
         "Expérience de test.", "observed", 0.8, "2026-11-14T10:20:00Z"),
    )

    # Supervised imitation records and one practice attempt.
    imitation = db.execute(
        """INSERT INTO imitation_examples
           (user_id,behavior,context,source_type,evidence,status,
            supervisor_approved,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        ("creator", "Répéter un mot", "apprentissage du langage",
         "demonstrated", "Démonstration enregistrée.", "practiced", 1,
         "2026-11-14T10:21:00Z", "2026-11-14T10:21:00Z"),
    ).lastrowid
    db.execute(
        """INSERT INTO imitation_attempts
           (user_id,example_id,result,evidence,successful,created_at)
           VALUES(?,?,?,?,?,?)""",
        ("creator", imitation, "Répétition correcte.",
         "Pratique supervisée.", 1, "2026-11-14T10:21:00Z"),
    )

    # Cognitive milestones, reasoning traces and metacognitive audits.
    db.execute(
        """INSERT INTO cognitive_milestones
           (user_id,stage_name,min_maturity,status,achieved_at)
           VALUES(?,?,?,?,?)""",
        ("creator", "observation", 0.2, "in_progress", None),
    )
    db.execute(
        """INSERT INTO cognitive_traces
           (user_id,thought_type,context_summary,decision_made,confidence,created_at)
           VALUES(?,?,?,?,?,?)""",
        ("creator", "reasoning", "Contexte de test.", "Observer avant de conclure.",
         0.85, "2026-11-14T10:22:00Z"),
    )
    db.execute(
        """INSERT INTO metacognition_logs
           (user_id,audit_type,confidence_average,confidence_trend,doubt_count,
            trace_count,findings,recommendations,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        ("creator", "test", 0.8, "stable", 1, 1, '{"finding":"test"}',
         '{"recommendation":"verify"}', "2026-11-14T10:22:00Z"),
    )

    # Affective history, decision journal and explicit preference evidence.
    db.execute(
        """INSERT INTO affective_history
           (user_id,source,event_label,state_json,created_at)
           VALUES(?,?,?,?,?)""",
        ("creator", "test", "interaction",
         '{"joy":40,"fear":10,"curiosity":75,"frustration":2,"sadness":3,"energy":95}',
         "2026-11-14T10:23:00Z"),
    )
    db.execute(
        """INSERT INTO decision_journal
           (user_id,question,options_json,chosen_option,reasons,evidence_json,
            confidence,outcome,status,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        ("creator", "Que faire ?", '["observer","demander"]', "observer",
         "Réduire l'incertitude.", '["observation-test"]', 0.8, "En attente",
         "chosen", "2026-11-14T10:23:00Z", "2026-11-14T10:23:00Z"),
    )
    db.execute(
        """INSERT INTO preference_evidence
           (user_id,domain,preference,evidence,basis,confidence,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        ("creator", "learning", "apprentissage progressif",
         "Préférence explicite de test.", "explicit_statement", 0.95,
         "2026-11-14T10:23:00Z"),
    )
    # Remaining core persistence tables: voice profile, journal, mood and maintenance.
    db.execute(
        """INSERT INTO voice_profiles
           (user_id,profile_name,embedding_json,created_at,updated_at)
           VALUES(?,?,?,?,?)""",
        ("creator", "voice-test", '[0.1,0.2,0.3]',
         "2026-11-14T10:24:00Z", "2026-11-14T10:24:00Z"),
    )
    db.execute(
        "INSERT INTO journal(user_id,entry,kind,created_at) VALUES(?,?,?,?)",
        ("creator", "Entrée de journal persistante.", "reflection",
         "2026-11-14T10:24:00Z"),
    )
    db.execute(
        """INSERT INTO mood_events
           (user_id,event,valence,arousal,created_at)
           VALUES(?,?,?,?,?)""",
        ("creator", "interaction de test", 0.7, 0.4, "2026-11-14T10:24:00Z"),
    )
    db.execute(
        """INSERT INTO maintenance_state
           (user_id,last_active_at,last_dream_at,updated_at)
           VALUES(?,?,?,?)""",
        ("creator", "2026-11-14T10:24:00Z", "2026-11-14T09:00:00Z",
         "2026-11-14T10:24:00Z"),
    )
    db.commit()


def test_full_chappie_schema_encrypted_backup_restore_roundtrip(
    tmp_path: Path, monkeypatch
) -> None:
    # Force a disposable local SQLite path and remove every possible remote
    # credential/selection so this test cannot contact production or test Turso.
    monkeypatch.setenv("CHAPPIE_STORAGE_BACKEND", "sqlite")
    for name in (
        "TURSO_DATABASE_URL",
        "TURSO_AUTH_TOKEN",
        "CHAPPIE_TEST_TURSO_DATABASE_URL",
        "CHAPPIE_TEST_TURSO_AUTH_TOKEN",
        "CHAPPIE_PRODUCTION_TURSO_DATABASE_URL",
        "CHAPPIE_ALLOW_TURSO_MIGRATION",
        "CHAPPIE_TURSO_CUTOVER_READY",
        "CHAPPIE_TURSO_FRESH_START",
        "CHAPPIE_TURSO_ADOPT_EXISTING_SCHEMA",
    ):
        monkeypatch.delenv(name, raising=False)

    import server

    source_path = tmp_path / "chappie-source.sqlite3"
    monkeypatch.setattr(server, "DB_PATH", source_path)
    monkeypatch.setattr(server, "STORAGE_MIGRATION_PENDING_CUTOVER", False)
    server.init_db()

    source = sqlite3.connect(source_path)
    source.execute("PRAGMA foreign_keys=ON")
    _seed_chappie_state(source)

    archive_path = tmp_path / "chappie-full-schema-backup.zip"
    encryption_key = "isolated-full-schema-test-key-2026"
    report = create_backup_archive(source, archive_path, encryption_key)
    assert report["encrypted"] is True
    assert report["verified_after_packaging"] is True

    with zipfile.ZipFile(archive_path, "r") as archive:
        assert set(archive.namelist()) == {
            "chappie-turso.json.enc",
            "chappie-turso.json.enc.sha256",
        }
        archive.extractall(tmp_path / "unpacked")

    encrypted_path = tmp_path / "unpacked" / "chappie-turso.json.enc"
    target = sqlite3.connect(tmp_path / "chappie-restored.sqlite3")
    target.execute("PRAGMA foreign_keys=ON")
    restored = restore_encrypted_logical_backup(
        target,
        encrypted_path,
        encryption_key,
        target_identity="chappie-full-schema-test.invalid",
        expected_target_identity="chappie-full-schema-test.invalid",
        production_identity="chappie-production.invalid",
    )

    source_schema = inspect_schema(source)
    target_schema = inspect_schema(target)
    schema_diff = compare_schemas(source_schema, target_schema)
    assert schema_diff["compatible"] is True, schema_diff
    assert restored["table_count"] == len(_user_tables(source))
    assert restored["total_rows"] == sum(
        source.execute(f"SELECT COUNT(*) FROM {_quote(table)}").fetchone()[0]
        for table in _user_tables(source)
    )
    assert restored["foreign_key_violations"] == 0

    # Compare every row in every application table, not just the seeded examples.
    for table in _user_tables(source):
        source_rows = source.execute(
            f"SELECT * FROM {_quote(table)} ORDER BY rowid"
        ).fetchall()
        target_rows = target.execute(
            f"SELECT * FROM {_quote(table)} ORDER BY rowid"
        ).fetchall()
        assert target_rows == source_rows, f"Rows differ after restore in {table}"

    # Verify that AUTOINCREMENT state survives, not merely the current rows.
    next_memory_id = target.execute(
        """INSERT INTO memories_v19
           (user_id,category,content,importance,source_type,confidence,
            tags,access_count,created_at,updated_at)
           VALUES('creator','test','post-restore sequence',1,'taught',0.8,
                  '[]',0,'2026-11-14T10:14:00Z','2026-11-14T10:14:00Z')"""
    ).lastrowid
    assert next_memory_id > 1

    target.close()
    source.close()
