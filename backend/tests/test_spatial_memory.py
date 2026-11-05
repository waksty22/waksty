import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from world.spatial_memory import (
    init_spatial_tables,
    start_location_session,
    stop_location_session,
    record_location,
    record_place_observation,
    confirm_place_identity,
    get_map_state,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_spatial_tables(conn)
    yield conn
    conn.close()


def test_location_requires_explicit_session_consent(db):
    with pytest.raises(ValueError):
        start_location_session(db, "creator", False)


def test_location_requires_active_session(db):
    with pytest.raises(ValueError):
        record_location(db, "creator", "missing", 48.1, -2.8)


def test_location_is_scoped_to_user_and_stops(db):
    session = start_location_session(db, "creator", True, "mobile")
    saved = record_location(
        db, "creator", session["session_id"], 48.1, -2.8,
        accuracy_m=12, recorded_at="2026-11-05T17:00:00+01:00",
    )
    assert saved["stored"] is True
    with pytest.raises(ValueError):
        record_location(db, "other", session["session_id"], 48.1, -2.8)
    stop_location_session(db, "creator", session["session_id"])
    with pytest.raises(ValueError):
        record_location(db, "creator", session["session_id"], 48.1, -2.8)
    state = get_map_state(db, "creator")
    assert state["statistics"]["location_samples"] == 1
    assert len(state["visits"]) == 1


def test_bad_coordinates_and_low_accuracy_are_rejected(db):
    session = start_location_session(db, "creator", True)
    sid = session["session_id"]
    with pytest.raises(ValueError):
        record_location(db, "creator", sid, 91, 0)
    with pytest.raises(ValueError):
        record_location(db, "creator", sid, 48, -2, accuracy_m=900)


def test_visual_place_is_stored_as_unconfirmed_observation(db):
    session = start_location_session(db, "creator", True)
    place = record_place_observation(
        db, "creator", "Un chemin bordé d'arbres et un banc bleu.",
        48.1, -2.8, confidence=0.4, session_id=session["session_id"],
    )
    assert place["identity_status"] == "unconfirmed"
    revisit = record_place_observation(
        db, "creator", "Un chemin bordé d'arbres et un banc bleu.",
        48.10001, -2.80001, confidence=0.4, session_id=session["session_id"],
    )
    assert revisit["identity_status"] == "candidate"
    assert revisit["candidate_place_id"] == place["place_id"]
    assert revisit["place_id"] == place["place_id"]
    assert revisit["observations_count"] == 2
    state = get_map_state(db, "creator")
    assert len(state["places"]) == 1
    assert state["places"][0]["place_id"] == revisit["place_id"]
    assert state["places"][0]["observations_count"] == 2
    assert state["visual_identity_is_not_automatically_confirmed"] is True
    confirmed = confirm_place_identity(
        db, "creator", revisit["place_id"], "Parc du quartier",
        "J'ai vérifié visuellement et confirmé manuellement ce lieu.",
    )
    assert confirmed["identity_status"] == "confirmed"
    confirmed_state = get_map_state(db, "creator")
    assert "vérifié" in confirmed_state["places"][0]["confirmation_evidence"]



def test_confirmed_place_is_not_silently_reidentified_on_similarity(db):
    first = record_place_observation(
        db, "creator", "Un grand bâtiment en pierre avec une tour.",
    )
    confirm_place_identity(
        db, "creator", first["place_id"], "Mairie",
        "Nom vérifié par le créateur.",
    )
    revisit = record_place_observation(
        db, "creator", "Un grand bâtiment en pierre avec une tour.",
    )
    assert revisit["place_id"] != first["place_id"]
    assert revisit["identity_status"] == "candidate"
    assert revisit["candidate_place_id"] == first["place_id"]
