import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from world.world_model import (
    add_world_relation,
    init_world_tables,
    upsert_world_entity,
)


def make_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_world_tables(db)
    return db


def test_confirmed_world_relation_cannot_be_downgraded_by_observation():
    db = make_db()
    upsert_world_entity(
        db, "creator", "person:creator", "person",
        {"label": "Créateur"}, source_type="taught", confidence=0.7,
    )
    upsert_world_entity(
        db, "creator", "place:home", "place",
        {"label": "Maison"}, source_type="taught", confidence=0.7,
    )

    confirmed = add_world_relation(
        db, "creator", "person:creator", "place:home",
        relation_type="lives_at", source_type="confirmed", confidence=0.75,
    )
    observed = add_world_relation(
        db, "creator", "person:creator", "place:home",
        relation_type="lives_at", source_type="observed", confidence=0.99,
    )

    assert confirmed["source_type"] == "confirmed"
    assert observed["source_type"] == "confirmed"
    assert observed["confidence"] == 0.99

    stored = db.execute(
        """SELECT source_type, confidence FROM world_relations
           WHERE user_id=? AND subject_id=? AND predicate=? AND object_id=?""",
        ("creator", "person:creator", "lives_at", "place:home"),
    ).fetchone()
    assert stored["source_type"] == "confirmed"
    assert stored["confidence"] == 0.99
    db.close()


def test_world_relations_remain_user_scoped():
    db = make_db()
    upsert_world_entity(
        db, "alice", "person:alice", "person", {"label": "Alice"},
        source_type="taught", confidence=0.8,
    )
    upsert_world_entity(
        db, "alice", "place:home", "place", {"label": "Maison"},
        source_type="taught", confidence=0.8,
    )
    relation = add_world_relation(
        db, "alice", "person:alice", "place:home",
        relation_type="visits", source_type="observed", confidence=0.5,
    )
    assert relation["user_id"] == "alice"
    assert db.execute(
        "SELECT COUNT(*) FROM world_relations WHERE user_id='bob'"
    ).fetchone()[0] == 0
    db.close()


def test_world_entity_search_orders_by_absolute_timestamp():
    from world.world_model import search_world_entities

    db = make_db()
    upsert_world_entity(
        db, "creator", "object:first", "object", {"label": "clock"},
        source_type="observed", confidence=0.5,
    )
    upsert_world_entity(
        db, "creator", "object:second", "object", {"label": "clock"},
        source_type="observed", confidence=0.5,
    )
    db.execute(
        "UPDATE world_entities SET last_observed_at=? WHERE id=?",
        ("2026-11-26T09:00:00+02:00", "object:first"),
    )
    db.execute(
        "UPDATE world_entities SET last_observed_at=? WHERE id=?",
        ("2026-11-26T08:30:00Z", "object:second"),
    )
    results = search_world_entities(db, "creator", "clock")
    assert [item["id"] for item in results] == ["object:second", "object:first"]
    db.close()


def test_entity_relations_order_by_absolute_timestamp():
    from world.world_model import get_entity_relations

    db = make_db()
    for entity_id, entity_type in (
        ("person:creator", "person"),
        ("place:home", "place"),
        ("place:work", "place"),
    ):
        upsert_world_entity(
            db, "creator", entity_id, entity_type, {"label": entity_id},
            source_type="taught", confidence=0.8,
        )
    add_world_relation(
        db, "creator", "person:creator", "place:home",
        relation_type="lives_at", source_type="observed", confidence=0.7,
    )
    add_world_relation(
        db, "creator", "person:creator", "place:work",
        relation_type="works_at", source_type="observed", confidence=0.7,
    )
    db.execute(
        "UPDATE world_relations SET updated_at=? WHERE predicate=?",
        ("2026-11-26T09:00:00+02:00", "lives_at"),
    )
    db.execute(
        "UPDATE world_relations SET updated_at=? WHERE predicate=?",
        ("2026-11-26T08:30:00Z", "works_at"),
    )
    results = get_entity_relations(db, "creator", "person:creator")
    assert [item["predicate"] for item in results] == ["works_at", "lives_at"]
    db.close()
