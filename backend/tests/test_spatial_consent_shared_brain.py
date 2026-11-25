import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cognition.shared_brain import get_shared_brain_snapshot


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE spatial_sessions (
            session_id TEXT PRIMARY KEY, user_id TEXT, device_label TEXT,
            consented INTEGER, started_at TEXT, ended_at TEXT, created_at TEXT
        );
        CREATE TABLE spatial_visits (
            id INTEGER PRIMARY KEY, user_id TEXT, session_id TEXT,
            latitude REAL, longitude REAL, accuracy_m REAL, altitude_m REAL,
            heading_deg REAL, speed_mps REAL, recorded_at TEXT, source TEXT,
            created_at TEXT
        );
        CREATE TABLE place_memories (
            place_id TEXT PRIMARY KEY, user_id TEXT, label TEXT,
            description TEXT, visual_signature TEXT, session_id TEXT,
            latitude REAL, longitude REAL, confidence REAL,
            identity_status TEXT, candidate_place_id TEXT, similarity_score REAL,
            confirmation_evidence TEXT, confirmed_at TEXT, first_seen_at TEXT,
            last_seen_at TEXT, observations_count INTEGER, created_at TEXT,
            updated_at TEXT
        );
    """)
    return db


def seed(db):
    db.executemany(
        "INSERT INTO spatial_sessions VALUES (?,?,?,?,?,?,?)",
        [
            ("allowed", "creator", "phone", 1, "2026-01-01", None, "t1"),
            ("denied", "creator", "phone", 0, "2026-01-02", None, "t2"),
            ("other-user", "alice", "phone", 1, "2026-01-03", None, "t3"),
        ],
    )
    db.executemany(
        "INSERT INTO spatial_visits VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "creator", "allowed", 48.1, -1.6, 10, None, None, None, "t1", "gps", "t1"),
            (2, "creator", "denied", 48.2, -1.7, 10, None, None, None, "t2", "gps", "t2"),
            (3, "alice", "other-user", 48.3, -1.8, 10, None, None, None, "t3", "gps", "t3"),
        ],
    )
    common = (0.8, "unconfirmed", None, 0.0, "", None, "t0", "t1", 1, "t0", "t1")
    db.executemany(
        "INSERT INTO place_memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("place-allowed", "creator", "parc", "un parc arboré", "parc arbres",
             "allowed", 48.1, -1.6, *common),
            ("place-denied", "creator", "musée", "un musée", "musée art",
             "denied", 48.2, -1.7, *common),
            ("place-visual", "creator", "tour", "une tour observée sans GPS",
             "tour pierre", None, None, None, *common),
            ("place-alice", "alice", "maison", "maison privée", "maison",
             "other-user", 48.3, -1.8, *common),
        ],
    )
    db.commit()


def test_shared_brain_never_exposes_spatial_records_from_nonconsented_sessions():
    db = make_db()
    seed(db)

    snapshot = get_shared_brain_snapshot(db, "creator", limit=20)
    assert {row["session_id"] for row in snapshot["spatial_sessions"]} == {"allowed"}
    assert {row["session_id"] for row in snapshot["spatial_visits"]} == {"allowed"}
    assert {row["place_id"] for row in snapshot["place_memories"]} == {
        "place-allowed", "place-visual"
    }
    assert all(row["user_id"] == "creator" for row in snapshot["place_memories"])
    db.close()


def test_query_aware_spatial_recall_keeps_consent_filtering():
    db = make_db()
    seed(db)

    snapshot = get_shared_brain_snapshot(
        db, "creator", limit=20, query="musée"
    )
    assert snapshot["spatial_sessions"]
    assert all(row["consented"] == 1 for row in snapshot["spatial_sessions"])
    assert all(row["session_id"] != "denied" for row in snapshot["spatial_visits"])
    assert all(row["place_id"] != "place-denied" for row in snapshot["place_memories"])
    db.close()
