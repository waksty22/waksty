"""Strict numeric validation for world-model confidence and pagination."""
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from world.world_model import (
    _normalize_limit,
    _validate_confidence,
    init_world_tables,
    search_world_entities,
    upsert_world_entity,
)


@pytest.mark.parametrize("bad_confidence", ["0.8", "1", True, False, None, [], {}])
def test_world_model_rejects_coerced_confidence_values(bad_confidence):
    with pytest.raises(ValueError, match="confidence"):
        _validate_confidence(bad_confidence)


@pytest.mark.parametrize("valid_confidence", [0, 1, 0.25, 0.8])
def test_world_model_accepts_real_numeric_confidence(valid_confidence):
    assert _validate_confidence(valid_confidence) == float(valid_confidence)


@pytest.mark.parametrize("bad_limit", ["10", 1.5, True, False, None, [], {}])
def test_world_model_rejects_coerced_limit_values(bad_limit):
    with pytest.raises(ValueError, match="limit"):
        _normalize_limit(bad_limit, 1, 100)


def test_world_model_still_clamps_valid_integer_limits():
    assert _normalize_limit(0, 1, 100) == 1
    assert _normalize_limit(150, 1, 100) == 100
    assert _normalize_limit(10, 1, 100) == 10


def test_world_entity_rejects_string_confidence_without_writing():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_world_tables(db)

    with pytest.raises(ValueError, match="confidence"):
        upsert_world_entity(
            db, "creator", "place:home", "place",
            {"label": "Maison"}, confidence="0.8",
        )
    assert db.execute("SELECT COUNT(*) FROM world_entities").fetchone()[0] == 0
    db.close()


def test_world_entity_search_rejects_string_limit():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    init_world_tables(db)

    with pytest.raises(ValueError, match="limit"):
        search_world_entities(db, "creator", "", limit="10")
    db.close()
