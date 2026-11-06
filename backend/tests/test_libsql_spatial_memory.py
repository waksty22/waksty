"""Real spatial-memory module integration tests against local libSQL only."""

import pytest

from storage.libsql_adapter import adapt_libsql_connection


@pytest.fixture
def spatial_db():
    libsql = pytest.importorskip("libsql")
    db = adapt_libsql_connection(libsql.connect(database=":memory:"))
    from world.spatial_memory import init_spatial_tables

    init_spatial_tables(db)
    try:
        yield db
    finally:
        db.close()


def test_real_libsql_spatial_location_consent_deduplication_and_user_scope(spatial_db):
    from world.spatial_memory import (
        get_map_state,
        record_location,
        start_location_session,
        stop_location_session,
    )

    with pytest.raises(ValueError, match="consentement"):
        start_location_session(spatial_db, "creator", False)

    session = start_location_session(
        spatial_db, "creator", True, device_label="test-device"
    )
    sid = session["session_id"]
    first = record_location(
        spatial_db, "creator", sid, 48.1, -2.8,
        accuracy_m=12, recorded_at="2026-11-07T10:00:00+01:00",
    )
    assert first["stored"] is True
    assert first["id"] is not None

    duplicate = record_location(
        spatial_db, "creator", sid, 48.1, -2.8,
        accuracy_m=12, recorded_at="2026-11-07T10:00:00+01:00",
    )
    assert duplicate == {"stored": False, "reason": "duplicate_timestamp"}

    with pytest.raises(ValueError, match="autorisée"):
        record_location(spatial_db, "another-user", sid, 48.1, -2.8)

    state = get_map_state(spatial_db, "creator")
    assert state["statistics"]["location_samples"] == 1
    assert state["visits"][0]["device_label"] == "test-device"
    assert state["tracking_requires_active_consent"] is True

    stop_location_session(spatial_db, "creator", sid)
    with pytest.raises(ValueError, match="active"):
        record_location(spatial_db, "creator", sid, 48.1, -2.8)


def test_real_libsql_spatial_place_observation_requires_human_confirmation(spatial_db):
    from world.spatial_memory import (
        confirm_place_identity,
        get_map_state,
        record_place_observation,
        start_location_session,
    )

    session = start_location_session(spatial_db, "creator", True, "mobile")
    sid = session["session_id"]
    description = "Un chemin bordé de grands arbres avec un banc bleu."

    first = record_place_observation(
        spatial_db, "creator", description,
        latitude=48.1, longitude=-2.8, confidence=0.4, session_id=sid,
    )
    assert first["identity_status"] == "unconfirmed"

    repeated = record_place_observation(
        spatial_db, "creator", description,
        latitude=48.10001, longitude=-2.80001,
        confidence=0.55, session_id=sid,
    )
    assert repeated["place_id"] == first["place_id"]
    assert repeated["identity_status"] == "candidate"
    assert repeated["observations_count"] == 2

    confirmed = confirm_place_identity(
        spatial_db, "creator", first["place_id"], "Parc de test",
        "Confirmation humaine explicite dans un test automatisé.",
    )
    assert confirmed["identity_status"] == "confirmed"
    assert confirmed["label"] == "Parc de test"

    state = get_map_state(spatial_db, "creator")
    assert state["statistics"]["known_place_observations"] == 1
    assert state["places"][0]["identity_status"] == "confirmed"
    assert state["places"][0]["confirmation_evidence"].startswith("Confirmation humaine")
    assert state["visual_identity_is_not_automatically_confirmed"] is True

    other_state = get_map_state(spatial_db, "another-user")
    assert other_state["statistics"]["location_samples"] == 0
    assert other_state["statistics"]["known_place_observations"] == 0
    assert other_state["places"] == []


def test_real_libsql_spatial_validation_rejects_unreliable_coordinates(spatial_db):
    from world.spatial_memory import record_location, start_location_session

    session = start_location_session(spatial_db, "creator", True)
    sid = session["session_id"]

    with pytest.raises(ValueError, match="hors limites"):
        record_location(spatial_db, "creator", sid, 91, 0)

    with pytest.raises(ValueError, match="Précision GPS insuffisante"):
        record_location(spatial_db, "creator", sid, 48.1, -2.8, accuracy_m=900)
